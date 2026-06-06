"""
Medication log safety logic  (TIER 1, feature #3).

Persistent dose tracking that ChatGPT structurally cannot do: given the doses a
caregiver has already logged, compute when the next dose is safe and block/warn on
a too-early re-dose or a 24-hour-cap breach. The interval and daily caps come from
the same authoritative table as the calculator (feature #2), so the guard and the
calculator can never disagree.

Pure functions only (no DB / FastAPI) so the guard can be unit tested directly.
The router in routers/medication.py persists doses and calls these functions.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.services.dosing import (
    normalize_drug_name,
    dose_interval_hours,
    daily_limits,
)

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

def _as_dt(value) -> datetime:
    """Accept a datetime or ISO string; return a timezone-aware UTC datetime."""
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _same_drug(a: str, b: str) -> bool:
    na, nb = normalize_drug_name(a), normalize_drug_name(b)
    if na and nb:
        return na == nb
    return a.strip().lower() == b.strip().lower()

def _doses_for_drug(drug: str, prior_doses: list) -> list:
    out = []
    for dose in prior_doses:
        d_drug = dose.get("drug") if isinstance(dose, dict) else getattr(dose, "drug", None)
        d_time = dose.get("given_at") if isinstance(dose, dict) else getattr(dose, "given_at", None)
        d_amt = dose.get("amount_mg") if isinstance(dose, dict) else getattr(dose, "amount_mg", None)
        if d_drug and d_time and _same_drug(d_drug, drug):
            out.append({"given_at": _as_dt(d_time), "amount_mg": d_amt})
    out.sort(key=lambda x: x["given_at"])
    return out

@dataclass
class NextDoseInfo:
    drug: str
    last_dose_at: Optional[str] = None
    next_safe_at: Optional[str] = None
    minutes_until_safe: int = 0
    is_due_now: bool = True
    interval_hours: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

def next_safe_dose(drug: str, prior_doses: list, now: Optional[datetime] = None) -> NextDoseInfo:
    now = now or _utcnow()
    interval = dose_interval_hours(drug)
    doses = _doses_for_drug(drug, prior_doses)
    if not doses or interval is None:
        return NextDoseInfo(drug=normalize_drug_name(drug) or drug,
                            is_due_now=True, interval_hours=interval)
    last = doses[-1]["given_at"]
    next_safe = last + timedelta(hours=interval)
    minutes = max(0, int((next_safe - now).total_seconds() // 60))
    return NextDoseInfo(
        drug=normalize_drug_name(drug) or drug,
        last_dose_at=last.isoformat(),
        next_safe_at=next_safe.isoformat(),
        minutes_until_safe=minutes,
        is_due_now=now >= next_safe,
        interval_hours=interval,
    )

@dataclass
class GuardResult:
    drug: str
    allowed: bool                    # False -> caregiver should NOT give the dose now
    too_early: bool = False
    exceeds_daily_count: bool = False
    exceeds_daily_mg: bool = False
    next_safe_at: Optional[str] = None
    minutes_until_safe: int = 0
    doses_in_last_24h: int = 0
    mg_in_last_24h: float = 0.0
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

def check_proposed_dose(
    drug: str,
    prior_doses: list,
    proposed_amount_mg: Optional[float] = None,
    weight_kg: Optional[float] = None,
    now: Optional[datetime] = None,
) -> GuardResult:
    """Deterministically decide whether giving `drug` right now is safe given the log."""
    now = now or _utcnow()
    canon = normalize_drug_name(drug) or drug
    interval = dose_interval_hours(drug)
    limits = daily_limits(drug, weight_kg) or {}
    doses = _doses_for_drug(drug, prior_doses)

    warnings: list[str] = []
    too_early = False
    next_safe_at = None
    minutes = 0

    if doses and interval is not None:
        last = doses[-1]["given_at"]
        next_safe = last + timedelta(hours=interval)
        if now < next_safe:
            too_early = True
            next_safe_at = next_safe.isoformat()
            minutes = max(0, int((next_safe - now).total_seconds() // 60))
            hrs, mins = divmod(minutes, 60)
            warnings.append(
                f"\u26a0 TOO EARLY: the last {canon} dose was at "
                f"{last.strftime('%H:%M UTC')}. The next dose is not safe until "
                f"{next_safe.strftime('%H:%M UTC')} (in {hrs}h {mins}m). Do not re-dose yet."
            )

    # 24-hour window counts
    window_start = now - timedelta(hours=24)
    in_window = [d for d in doses if d["given_at"] >= window_start]
    count_24h = len(in_window)
    mg_24h = sum((d["amount_mg"] or 0) for d in in_window)

    exceeds_count = False
    if limits.get("max_doses_per_24h") is not None:
        if count_24h + 1 > limits["max_doses_per_24h"]:
            exceeds_count = True
            warnings.append(
                f"\u26a0 DAILY LIMIT: {count_24h} {canon} dose(s) already given in the last 24h. "
                f"The maximum is {limits['max_doses_per_24h']} in 24 hours. Do not give more \u2014 "
                "call your pediatrician if symptoms persist."
            )

    exceeds_mg = False
    if proposed_amount_mg and limits.get("max_mg_per_24h") is not None:
        if mg_24h + proposed_amount_mg > limits["max_mg_per_24h"]:
            exceeds_mg = True
            warnings.append(
                f"\u26a0 DAILY LIMIT: this dose would bring the 24-hour total to "
                f"{mg_24h + proposed_amount_mg:g} mg, above the {limits['max_mg_per_24h']:g} mg "
                f"daily maximum for {canon}. Do not give it."
            )

    allowed = not (too_early or exceeds_count or exceeds_mg)
    return GuardResult(
        drug=canon, allowed=allowed, too_early=too_early,
        exceeds_daily_count=exceeds_count, exceeds_daily_mg=exceeds_mg,
        next_safe_at=next_safe_at, minutes_until_safe=minutes,
        doses_in_last_24h=count_24h, mg_in_last_24h=round(mg_24h, 1),
        warnings=warnings,
    )
