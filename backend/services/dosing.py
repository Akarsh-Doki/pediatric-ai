"""
Deterministic weight-based OTC dose calculator  (TIER 1, feature #2).

SAFETY CONTRACT (do not weaken):
  * Doses are COMPUTED IN CODE from an authoritative published dosing table
    (backend/data/medication/dosing_table.json). The LLM never produces a dose
    number; it may only route a parent to this calculator.
  * Limited to acetaminophen and ibuprofen (standard OTC antipyretics).
  * Aspirin is NEVER dosed for a child (Reye's syndrome). Any other drug is refused.
  * A current weight is REQUIRED. No weight -> no dose.
  * Age floors are enforced: ibuprofen is refused under 6 months (hard floor);
    acetaminophen under 3 months is deferred to a clinician.
  * Every numeric result is bounded by a hard max single dose and a max daily dose.
  * Every result carries a disclaimer to confirm with the product label / pediatrician.

This module has NO dependency on FastAPI / SQLAlchemy / the LLM so it can be unit
tested in complete isolation, which is the whole point: safety-critical arithmetic
must be deterministic and independently verifiable.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "medication" / "dosing_table.json"

LB_TO_KG = 0.45359237

# Condition-flag keys (substrings) that should DEFER to a clinician (no number)
# rather than merely warn. Everything else in the table's condition_flags is a caution.
_DEFER_CONDITION_KEYS = {
    "acetaminophen": {"liver disease", "hepatic"},
    "ibuprofen": {"kidney disease", "renal"},
}

# Minimal brand/synonym normalization for the two supported drugs + the one
# forbidden drug. (The richer normalizer lives in medication_safety.py; dosing is
# kept self-contained so it can be tested with zero other imports.)
_DOSE_NAME_MAP = {
    "acetaminophen": "acetaminophen",
    "paracetamol": "acetaminophen",
    "tylenol": "acetaminophen",
    "apap": "acetaminophen",
    "ibuprofen": "ibuprofen",
    "motrin": "ibuprofen",
    "advil": "ibuprofen",
    "nurofen": "ibuprofen",
    "aspirin": "aspirin",
    "asa": "aspirin",
    "bayer": "aspirin",
    "acetylsalicylic acid": "aspirin",
}


@lru_cache(maxsize=1)
def _load_table() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)

def lb_to_kg(pounds: float) -> float:
    """Convert pounds to kilograms (parents usually weigh in lb)."""
    return round(pounds * LB_TO_KG, 3)

def normalize_drug_name(raw: str) -> Optional[str]:
    """Map a brand/synonym to a canonical name this calculator understands.

    Returns 'acetaminophen', 'ibuprofen', 'aspirin', or None (unknown/unsupported).
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _DOSE_NAME_MAP:
        return _DOSE_NAME_MAP[key]
    # tolerate trailing words like "tylenol liquid" / "children's motrin"
    for token, canon in _DOSE_NAME_MAP.items():
        if token in key:
            return canon
    return None

def _round_to_step(value: float, step: float) -> float:
    """Round half-up to the nearest `step`."""
    if step <= 0:
        return round(value, 3)
    return round(math.floor(value / step + 0.5) * step, 3)

def _floor_to_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(math.floor(value / step) * step, 3)

def _bounded_dose_mg(raw_mg: float, max_single_mg: float, step: float) -> float:
    """Round to a clinical increment and guarantee we never exceed the hard cap."""
    capped = min(raw_mg, max_single_mg)
    rounded = _round_to_step(capped, step)
    if rounded > max_single_mg:               # rounding pushed us over the cap
        rounded = _floor_to_step(max_single_mg, step)
    return rounded

def _mg_to_ml(mg: float, conc_mg: float, conc_ml: float, step: float) -> float:
    if conc_mg <= 0:
        return 0.0
    return _round_to_step(mg / conc_mg * conc_ml, step)

@dataclass
class DoseResult:
    drug: str                          # canonical name, or the echoed input if unsupported
    ok: bool                           # True only when a numeric dose is provided
    status: str                        # "ok" | "refused"
    display_name: Optional[str] = None
    single_dose_mg: Optional[float] = None
    single_dose_mg_range: Optional[list] = None   # [low, high] acceptable mg range
    single_dose_ml: Optional[float] = None
    concentration_label: Optional[str] = None
    interval_hours: Optional[int] = None
    interval_display: Optional[str] = None
    max_doses_per_24h: Optional[int] = None
    max_mg_per_24h: Optional[float] = None
    weight_kg: Optional[float] = None
    age_months: Optional[int] = None
    reasons: list = field(default_factory=list)     # why refused (if refused)
    warnings: list = field(default_factory=list)    # cautions shown alongside a dose
    disclaimer: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

def _refuse(drug: str, reason: str, **echo) -> DoseResult:
    table = _load_table()
    return DoseResult(
        drug=drug, ok=False, status="refused",
        reasons=[reason], disclaimer=table["global_disclaimer"], **echo,
    )

def _age_to_months(age_months: Optional[int], age_years: Optional[float]) -> Optional[int]:
    if age_months is not None:
        return int(age_months)
    if age_years is not None:
        return int(round(age_years * 12))
    return None

def compute_dose(
    drug: str,
    weight_kg: Optional[float] = None,
    age_months: Optional[int] = None,
    age_years: Optional[float] = None,
    known_conditions: Optional[list] = None,
    weight_lb: Optional[float] = None,
) -> DoseResult:
    """Compute a single OTC antipyretic dose deterministically.

    Provide weight in kg (preferred) or lb. Provide age in months or years if known
    (used only to enforce age floors). known_conditions is the patient's condition list.
    """
    table = _load_table()
    known_conditions = [c.lower() for c in (known_conditions or [])]

    if weight_kg is None and weight_lb is not None:
        weight_kg = lb_to_kg(weight_lb)

    canon = normalize_drug_name(drug)
    age_m = _age_to_months(age_months, age_years)

    # --- forbidden / unsupported drug -------------------------------------
    if canon == "aspirin":
        return _refuse(drug, table["forbidden_drugs"]["aspirin"],
                       weight_kg=weight_kg, age_months=age_m)
    if canon not in ("acetaminophen", "ibuprofen"):
        return _refuse(
            drug,
            "This calculator only provides doses for acetaminophen (Tylenol) and "
            "ibuprofen (Motrin/Advil). For anything else, please ask your pediatrician "
            "or pharmacist.",
            weight_kg=weight_kg, age_months=age_m,
        )

    d = table["drugs"][canon]

    # --- weight required --------------------------------------------------
    if weight_kg is None or weight_kg <= 0:
        return _refuse(
            canon,
            "A current weight is required to calculate a safe dose. Please weigh your "
            "child (or use their most recent weight) and try again.",
            display_name=d["display_name"], age_months=age_m,
        )
    if weight_kg > 150:
        return _refuse(
            canon,
            f"The weight entered ({weight_kg} kg) looks unusually high for a child. "
            "Please double-check the value and units.",
            display_name=d["display_name"], age_months=age_m,
        )

    # --- age floor --------------------------------------------------------
    defer_under = d.get("defer_to_clinician_under_months")
    if age_m is not None and defer_under is not None and age_m < defer_under:
        return _refuse(canon, d["defer_reason_under_age"],
                       display_name=d["display_name"], weight_kg=weight_kg, age_months=age_m)

    warnings: list[str] = []
    if age_m is None:
        if canon == "ibuprofen":
            warnings.append(
                "Ibuprofen must NOT be given under 6 months of age. Confirm your child "
                "is at least 6 months old before giving this dose."
            )
        else:
            warnings.append(
                "For babies under 3 months, do not dose at home \u2014 call your pediatrician. "
                "Confirm your child's age before giving this dose."
            )

    # --- condition flags (defer for serious ones, caution otherwise) ------
    defer_keys = _DEFER_CONDITION_KEYS.get(canon, set())
    for flag_key, flag_msg in d.get("condition_flags", {}).items():
        if any(flag_key in cond for cond in known_conditions):
            if flag_key in defer_keys:
                return _refuse(canon, flag_msg, display_name=d["display_name"],
                               weight_kg=weight_kg, age_months=age_m)
            warnings.append(flag_msg)

    # --- the actual arithmetic (bounded) ----------------------------------
    step_mg = table["rounding"]["mg_round_to_nearest"]
    step_ml = table["rounding"]["ml_round_to_nearest"]

    target_mg = _bounded_dose_mg(d["mg_per_kg_per_dose"] * weight_kg, d["max_single_dose_mg"], step_mg)
    low_mg = _bounded_dose_mg(d["mg_per_kg_per_dose_min"] * weight_kg, d["max_single_dose_mg"], step_mg)
    if low_mg > target_mg:
        low_mg = target_mg

    dose_ml = _mg_to_ml(target_mg, d["liquid_concentration_mg"], d["liquid_concentration_ml"], step_ml)

    max_daily_mg = _floor_to_step(
        min(d["max_mg_per_kg_per_24h"] * weight_kg, d["absolute_max_mg_per_24h"]), step_mg
    )

    # --- standard cautions every time -------------------------------------
    warnings.append(
        f"Do not give more than {int(d['max_doses_per_24h'])} doses in 24 hours, and never "
        f"more than {max_daily_mg:g} mg total in 24 hours."
    )
    warnings.append(
        f"Use the dosing syringe that comes with the medicine and confirm the concentration "
        f"on YOUR bottle ({d['concentration_label']}); liquid strengths differ between products."
    )
    if canon == "ibuprofen":
        warnings.append("Give ibuprofen with food or milk, and make sure your child is drinking well.")

    return DoseResult(
        drug=canon,
        ok=True,
        status="ok",
        display_name=d["display_name"],
        single_dose_mg=target_mg,
        single_dose_mg_range=[low_mg, target_mg],
        single_dose_ml=dose_ml,
        concentration_label=d["concentration_label"],
        interval_hours=int(d["min_interval_hours"]),
        interval_display=d["interval_display"],
        max_doses_per_24h=int(d["max_doses_per_24h"]),
        max_mg_per_24h=max_daily_mg,
        weight_kg=round(weight_kg, 2),
        age_months=age_m,
        warnings=warnings,
        disclaimer=table["global_disclaimer"],
    )


def dose_interval_hours(drug: str) -> Optional[int]:
    """Minimum safe re-dose interval (hours) for the double-dose guard (feature #3)."""
    canon = normalize_drug_name(drug)
    table = _load_table()
    if canon in table["drugs"]:
        return int(table["drugs"][canon]["min_interval_hours"])
    return None


def max_doses_per_24h(drug: str) -> Optional[int]:
    canon = normalize_drug_name(drug)
    table = _load_table()
    if canon in table["drugs"]:
        return int(table["drugs"][canon]["max_doses_per_24h"])
    return None


def daily_limits(drug: str, weight_kg: Optional[float] = None) -> Optional[dict]:
    """Return {'max_doses_per_24h', 'max_mg_per_24h'} for the double-dose guard.

    max_mg_per_24h uses the weight-based per-kg cap when a weight is supplied,
    otherwise the absolute ceiling.
    """
    canon = normalize_drug_name(drug)
    table = _load_table()
    if canon not in table["drugs"]:
        return None
    d = table["drugs"][canon]
    step = table["rounding"]["mg_round_to_nearest"]
    if weight_kg and weight_kg > 0:
        max_mg = _floor_to_step(min(d["max_mg_per_kg_per_24h"] * weight_kg, d["absolute_max_mg_per_24h"]), step)
    else:
        max_mg = d["absolute_max_mg_per_24h"]
    return {"max_doses_per_24h": int(d["max_doses_per_24h"]), "max_mg_per_24h": max_mg}


def supported_drugs() -> list:
    return list(_load_table()["drugs"].keys())
