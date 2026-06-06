"""
Deterministic medication safety layer  (TIER 1, feature #1 \u2014 the flagship).

Whenever a medication is mentioned or about to be recommended, this service
cross-checks it IN CODE against the patient's allergies, current medications, age,
and known conditions, and returns hard, structured warnings:

  * allergy conflict            (BLOCK)   \u2014 candidate matches a documented allergy
  * pediatric contraindication  (BLOCK)   \u2014 e.g. aspirin in a child (Reye's)
  * duplicate active ingredient (HIGH)    \u2014 incl. ingredients HIDDEN inside combo products
  * drug-drug interaction       (HIGH/MOD)
  * allergy cross-reactivity    (CAUTION)
  * unknown drug                (INFO)    \u2014 couldn't verify, advise caution

The point of doing this in code (vs. hoping the LLM noticed a pasted allergy) is that
deterministic code cannot silently miss it. The checks below run with ZERO network
dependency. An optional enrich_from_apis() can normalize names via RxNorm/RxNav and
pull label text via openFDA when network is available, with caching, but no safety
decision depends on it.

No FastAPI / SQLAlchemy / LLM imports here \u2014 fully unit-testable in isolation.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from functools import lru_cache
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "medication" / "drug_data.json"

# Severity ordering (higher = more serious). "block" stops a recommendation.
_SEVERITY_RANK = {"info": 0, "caution": 1, "moderate": 2, "high": 3, "block": 4}

# Filler words stripped before product/ingredient lookup.
_FILLER = {
    "childrens", "children", "child", "infant", "infants", "junior", "jr", "adult",
    "liquid", "chewable", "chewables", "suspension", "drops", "tablet", "tablets",
    "caplet", "caplets", "softgel", "softgels", "oral", "pediatric", "extra", "strength",
    "mg", "ml", "the", "a", "some", "of", "my",
}

@lru_cache(maxsize=1)
def _load_data() -> dict:
    with open(_DATA_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)

def _clean(name: str) -> str:
    s = name.lower().strip()
    s = s.replace("&", " and ").replace("/", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _FILLER]
    return " ".join(tokens)

def normalize_to_ingredients(name: str) -> list:
    """Resolve a brand/product/ingredient name to its set of active ingredients.

    Catches hidden ingredients inside combination products (e.g. acetaminophen inside
    'Children's Tylenol Cold'). Returns [] if the name can't be resolved.
    """
    data = _load_data()
    products = data["products"]
    synonyms = data["ingredient_synonyms"]

    cleaned = _clean(name)
    if not cleaned:
        return []

    # 1) exact product / ingredient match on the cleaned string
    if cleaned in products:
        return list(dict.fromkeys(products[cleaned]))
    if cleaned in synonyms:
        return [synonyms[cleaned]]

    # 2) longest-match scan: prefer multiword product keys over single ingredients
    found: list[str] = []
    for key in sorted(products.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", cleaned):
            found.extend(products[key])
    if not found:
        for key in sorted(synonyms.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", cleaned):
                found.append(synonyms[key])
    return list(dict.fromkeys(found))

def _classes_for(ingredient: str) -> set:
    data = _load_data()
    return set(data["drug_classes"].get(ingredient, [])) | {ingredient}

def _med_name(med) -> str:
    if isinstance(med, dict):
        return str(med.get("name", "")) or str(med)
    return str(med)

def _patient_allergen_classes(known_conditions: list) -> dict:
    """From the condition list, return {allergen_label: set(classes)} for allergy entries."""
    data = _load_data()
    allergy_terms = data["allergy_terms"]
    result: dict[str, set] = {}
    for cond in known_conditions:
        c = cond.lower()
        # treat as an allergy if it says "allerg" OR directly names a known allergen term
        is_allergy = "allerg" in c
        for term, classes in allergy_terms.items():
            if re.search(rf"\b{re.escape(term)}\b", c) and (is_allergy or term in c):
                result.setdefault(term, set()).update(classes)
    return result

@dataclass
class Warning_:
    type: str            # allergy | pediatric_contraindication | duplicate_ingredient | interaction | cross_reactivity | unknown_drug
    severity: str        # block | high | moderate | caution | info
    message: str
    ingredient: Optional[str] = None
    related: Optional[str] = None     # the other med / allergen involved

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class SafetyResult:
    drug: str
    ingredients: list
    safe: bool                       # True only if NO blocking warning
    blocked: bool                    # True if any severity == "block"
    max_severity: str
    warnings: list                   # list[dict]
    checked_against: dict            # echo of what we compared with

    def to_dict(self) -> dict:
        return asdict(self)

def check_medication(patient: dict, drug: str) -> SafetyResult:
    """Deterministically screen `drug` against this patient. Pure, no network.

    patient: {"age": int(years) | "age_years": float, "known_conditions": [...],
              "medications": [{"name": ...} | "..."]}
    """
    known_conditions = [str(c) for c in (patient.get("known_conditions") or [])]
    current_meds = patient.get("medications") or []
    age_years = patient.get("age_years")
    if age_years is None:
        age_years = patient.get("age")

    candidate_ingredients = normalize_to_ingredients(drug)
    warnings: list[Warning_] = []

    if not candidate_ingredients:
        warnings.append(Warning_(
            type="unknown_drug", severity="info",
            message=(f"\u201c{drug}\u201d isn't in the safety database, so it could not be checked "
                     "automatically against allergies or other medicines. Please confirm with "
                     "your pediatrician or pharmacist before giving it."),
        ))
        return _finalize(drug, candidate_ingredients, warnings, known_conditions, current_meds, age_years)

    data = _load_data()

    # ---- 1) pediatric contraindication (e.g. aspirin in a child) ----------
    contra = data.get("pediatric_contraindications", {})
    for ing in candidate_ingredients:
        if ing in contra:
            rule = contra[ing]
            if age_years is None or age_years < rule["max_age_years_under"]:
                warnings.append(Warning_(
                    type="pediatric_contraindication",
                    severity="block", ingredient=ing, message=rule["reason"],
                ))

    # ---- 2) allergy conflict + cross-reactivity ---------------------------
    allergens = _patient_allergen_classes(known_conditions)
    cross = data.get("allergy_cross_reactivity", [])
    for ing in candidate_ingredients:
        ing_classes = _classes_for(ing)
        for allergen_label, allergen_classes in allergens.items():
            if ing_classes & allergen_classes:
                warnings.append(Warning_(
                    type="allergy", severity="block", ingredient=ing, related=allergen_label,
                    message=(f"\u26a0 ALLERGY CONFLICT: {ing} matches a documented allergy "
                             f"(\u201c{allergen_label}\u201d). Do NOT give this without your "
                             "pediatrician's explicit approval."),
                ))
            else:
                for rule in cross:
                    if rule["allergen_class"] in allergen_classes and rule["reacts_with_class"] in ing_classes:
                        warnings.append(Warning_(
                            type="cross_reactivity", severity=rule["severity"],
                            ingredient=ing, related=allergen_label, message=rule["note"],
                        ))

    # ---- 3) duplicate active ingredient (incl. hidden in combos) ----------
    for med in current_meds:
        med_name = _med_name(med)
        med_ings = set(normalize_to_ingredients(med_name))
        shared = med_ings & set(candidate_ingredients)
        for ing in sorted(shared):
            warnings.append(Warning_(
                type="duplicate_ingredient", severity="high", ingredient=ing, related=med_name,
                message=(f"DUPLICATE INGREDIENT: your child already takes \u201c{med_name}\u201d, which "
                         f"contains {ing}. Giving more {ing} on top of it risks an overdose. "
                         "Check both labels and do not double up."),
            ))

    # ---- 4) drug-drug interactions ---------------------------------------
    interactions = data.get("interactions", [])
    current_ingredient_set = set()
    for med in current_meds:
        current_ingredient_set.update(normalize_to_ingredients(_med_name(med)))
    for ing in candidate_ingredients:
        for other in current_ingredient_set:
            if other == ing:
                continue
            for rule in interactions:
                pair = {rule["a"], rule["b"]}
                if pair == {ing, other}:
                    warnings.append(Warning_(
                        type="interaction", severity=rule["severity"],
                        ingredient=ing, related=other, message=rule["note"],
                    ))

    # de-duplicate identical warnings (same type+ingredient+related)
    seen = set()
    deduped = []
    for w in warnings:
        k = (w.type, w.ingredient, w.related)
        if k not in seen:
            seen.add(k)
            deduped.append(w)

    return _finalize(drug, candidate_ingredients, deduped, known_conditions, current_meds, age_years)


def _finalize(drug, ingredients, warnings, known_conditions, current_meds, age_years) -> SafetyResult:
    max_sev = "info"
    for w in warnings:
        if _SEVERITY_RANK[w.severity] > _SEVERITY_RANK[max_sev]:
            max_sev = w.severity
    blocked = any(w.severity == "block" for w in warnings)
    # "safe" means nothing that should stop the recommendation; info-only counts as safe.
    safe = not blocked and not any(w.severity in ("high",) for w in warnings)
    return SafetyResult(
        drug=drug,
        ingredients=ingredients,
        safe=safe,
        blocked=blocked,
        max_severity=max_sev if warnings else "none",
        warnings=[w.to_dict() for w in warnings],
        checked_against={
            "known_conditions": known_conditions,
            "current_medications": [_med_name(m) for m in current_meds],
            "age_years": age_years,
        },
    )

# --------------------------------------------------------------------------
# Free-text scan: find medication mentions in a chat message so the chat
# pipeline can run check_medication() on each (feature #1 "called before any
# medication content is shown to the user").
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _mention_vocabulary() -> list:
    data = _load_data()
    vocab = set(data["ingredient_synonyms"].keys()) | set(data["products"].keys())
    # longest first so "tylenol cold" wins over "tylenol"
    return sorted(vocab, key=len, reverse=True)

def scan_text_for_medications(text: str) -> list:
    """Return the distinct medication names mentioned in free text."""
    cleaned = _clean(text)
    hits: list[str] = []
    for term in _mention_vocabulary():
        if re.search(rf"\b{re.escape(term)}\b", cleaned):
            hits.append(term)
    # collapse: drop a hit if it's a substring token-set of a longer hit already kept
    kept: list[str] = []
    for h in hits:
        if not any(h != k and re.search(rf"\b{re.escape(h)}\b", k) for k in hits):
            kept.append(h)
    return list(dict.fromkeys(kept))

# --------------------------------------------------------------------------
# OPTIONAL enrichment (RxNorm/RxNav + openFDA). Network-guarded + cached.
# No safety decision depends on this; it only adds reference info when online.
# --------------------------------------------------------------------------
_API_CACHE: dict[str, dict] = {}
_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "medication" / "_api_cache.json"

def _load_cache() -> dict:
    global _API_CACHE
    if _API_CACHE:
        return _API_CACHE
    try:
        if _CACHE_FILE.exists():
            _API_CACHE = json.loads(_CACHE_FILE.read_text())
    except Exception:
        _API_CACHE = {}
    return _API_CACHE

def _save_cache() -> None:
    try:
        _CACHE_FILE.write_text(json.dumps(_API_CACHE, indent=2))
    except Exception:
        pass

def enrich_from_apis(name: str, timeout: float = 4.0) -> Optional[dict]:
    """Best-effort RxNorm (rxcui) + openFDA label lookup. Returns None on any failure
    (e.g. offline). Cached on disk. NEVER used for a safety decision."""
    cache = _load_cache()
    key = name.strip().lower()
    if key in cache:
        return cache[key]
    try:
        import requests  # local import: importing this module must not require network/libs
        result: dict = {"name": name}
        r = requests.get(
            "https://rxnav.nlm.nih.gov/REST/rxcui.json",
            params={"name": name, "search": 2}, timeout=timeout,
        )
        if r.ok:
            ids = (r.json().get("idGroup", {}) or {}).get("rxnormId", [])
            result["rxcui"] = ids[0] if ids else None
        fda = requests.get(
            "https://api.fda.gov/drug/label.json",
            params={"search": f"openfda.generic_name:{name}", "limit": 1}, timeout=timeout,
        )
        if fda.ok:
            res = fda.json().get("results", [])
            if res:
                lbl = res[0]
                result["warnings_text"] = (lbl.get("warnings") or [None])[0]
                result["drug_interactions_text"] = (lbl.get("drug_interactions") or [None])[0]
        cache[key] = result
        _save_cache()
        return result
    except Exception:
        return None
