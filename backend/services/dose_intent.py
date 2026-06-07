"""
backend/services/dose_intent.py

Detects when a chat message is asking *how much* of a known OTC antipyretic to give,
pulls out the drug + weight + age, and hands off to the deterministic dosing engine.
The chat router uses this so dose questions are answered from compute_dose (code) rather
than from the language model -- the milligrams are never hallucinated.

Design notes:
  * Only *dose-quantity* questions trigger this ("how much", "what dose", "calculate",
    "dosage"...). A plain "can I give...?" is a safety question and is intentionally NOT
    matched here -- the RAG answer + the safety scan already handle that.
  * Only the drugs the calculator knows are matched (acetaminophen, ibuprofen, aspirin).
    Aspirin is included on purpose: routing it to compute_dose yields a deterministic
    Reye's refusal instead of a model guess. Anything else falls through to RAG.
"""
import re
from typing import Optional

from backend.services.dosing import compute_dose, lb_to_kg, DoseResult  # noqa: F401 (compute_dose re-exported for callers)

# Drug families the calculator can speak to, mapped to the canonical name compute_dose uses.
_DRUG_TERMS = {
    "acetaminophen": ("acetaminophen", "tylenol", "paracetamol", "tempra", "feverall"),
    "ibuprofen": ("ibuprofen", "motrin", "advil", "nuprin"),
    "aspirin": ("aspirin", "acetylsalicylic", "bayer"),
}

# A dose *quantity* question -- not just any mention of a drug.
_INTENT_RE = re.compile(
    r"\b(how much|how many|dosage|calculate|"
    r"(?:what(?:'s| is)?(?: the)?|the|right|correct|proper|safe|recommended)\s+dose|"
    r"dose of)\b",
    re.I,
)

_WEIGHT_LB_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds)\b", re.I)
_WEIGHT_KG_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|kgs|kilo|kilos|kilogram|kilograms)\b", re.I)
_AGE_MONTH_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:month|months|mo|mos|mth|mths)\b", re.I)
_AGE_HYPHEN_RE = re.compile(r"(\d+(?:\.\d+)?)[- ]year[- ]old", re.I)
_AGE_YEAR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:year|years|yr|yrs|yo|y/o|y\.o\.)\b", re.I)


def _find_drug(text: str) -> Optional[str]:
    low = " " + text.lower() + " "
    for canonical, terms in _DRUG_TERMS.items():
        for term in terms:
            if re.search(r"\b" + re.escape(term) + r"\b", low):
                return canonical
    return None


def _find_weight_kg(text: str) -> Optional[float]:
    m = _WEIGHT_KG_RE.search(text)
    if m:
        return round(float(m.group(1)), 2)
    m = _WEIGHT_LB_RE.search(text)
    if m:
        return round(lb_to_kg(float(m.group(1))), 2)
    return None


def _find_age(text: str):
    """Return (age_months, age_years); months wins if both somehow present."""
    m = _AGE_MONTH_RE.search(text)
    if m:
        return (int(round(float(m.group(1)))), None)
    m = _AGE_HYPHEN_RE.search(text) or _AGE_YEAR_RE.search(text)
    if m:
        return (None, float(m.group(1)))
    return (None, None)


def parse_dose_request(message: str, patient_info: Optional[dict]) -> Optional[dict]:
    """Return a dose-request dict if `message` is asking how much of a known drug to give,
    else None. Weight/age are read from the message first, then the patient record."""
    if not message or not _INTENT_RE.search(message):
        return None
    drug = _find_drug(message)
    if not drug:
        return None

    info = patient_info or {}

    weight_kg = _find_weight_kg(message)
    if weight_kg is None:
        pw = info.get("weight_kg")
        weight_kg = round(float(pw), 2) if pw else None

    age_months, age_years = _find_age(message)
    if age_months is None and age_years is None and info.get("age") is not None:
        age_years = float(info["age"])

    return {
        "drug": drug,
        "weight_kg": weight_kg,
        "age_months": age_months,
        "age_years": age_years,
        "known_conditions": info.get("known_conditions") or [],
    }


def need_weight_message(drug: str) -> str:
    return (
        f"I can work out a dose of {drug} for you. First, what does your child weigh? "
        f"Pediatric dosing is based on weight, not age, so I need the weight "
        f"(in pounds or kilograms) before I can give you a safe number."
    )


def format_dose_answer(r: DoseResult, child_name: Optional[str] = None) -> str:
    """Turn a DoseResult into a warm, plain-text answer (no markdown -- it is also spoken)."""
    if not r.ok:
        reason = " ".join(r.reasons) if r.reasons else "I'm not able to calculate this dose safely."
        return (reason + " " + (r.disclaimer or "")).strip()

    drug = r.display_name or r.drug
    sentence = (
        f"For a child weighing about {r.weight_kg} kg, a typical dose of {drug} is "
        f"around {int(round(r.single_dose_mg))} mg"
    )
    if r.single_dose_ml is not None and r.concentration_label:
        sentence += f" - about {r.single_dose_ml} mL of {r.concentration_label}"
    if r.interval_display:
        sentence += f", {r.interval_display}"
    sentence += "."

    parts = [sentence]
    # The dosing engine already authors the daily-cap / syringe / food cautions in
    # r.warnings -- we surface those verbatim rather than re-deriving (and duplicating) them.
    if r.warnings:
        parts.append(" ".join(r.warnings))
    elif r.max_doses_per_24h and r.max_mg_per_24h:
        parts.append(
            f"Do not give more than {r.max_doses_per_24h} doses or "
            f"{int(round(r.max_mg_per_24h))} mg in 24 hours."
        )
    if r.disclaimer:
        parts.append(r.disclaimer)
    return " ".join(parts)


def format_safety_block(blocking_payloads: list) -> str:
    """Message shown when a documented allergy/contraindication vetoes the dose entirely."""
    msgs = []
    for p in blocking_payloads:
        for w in p.get("warnings", []):
            if w.get("severity") == "block" and w.get("message"):
                msgs.append(w["message"])
    joined = " ".join(msgs)
    return (
        (joined + " " if joined else "")
        + "Because of that, I won't calculate a dose for this medicine. "
        "Please check with your pediatrician or pharmacist before giving it."
    )
