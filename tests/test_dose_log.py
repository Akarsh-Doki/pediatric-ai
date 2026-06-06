"""Tests for the medication-log double-dose guard (TIER 1, feature #3).

This is the safety guarantee ChatGPT structurally can't provide: it doesn't remember
the 2 p.m. dose. Given a log of prior doses, the guard must block a too-early re-dose,
block a 24-hour-cap breach (by count OR by milligrams), allow a dose once the interval
has elapsed, and compute the correct "next safe at" countdown.

All times are pinned explicitly (no wall-clock dependence) so the suite is deterministic
under repo pytest and under the offline stdlib runner.
"""
from datetime import datetime, timedelta, timezone

from backend.services.dose_log import check_proposed_dose, next_safe_dose

NOW = datetime(2026, 6, 2, 18, 0, tzinfo=timezone.utc)


def _ago(hours):
    return (NOW - timedelta(hours=hours)).isoformat()


class TestTooEarlyGuard:
    def test_redose_within_interval_blocked(self):
        # Ibuprofen interval is 6h; a dose was given 2h ago -> not yet safe.
        log = [{"drug": "ibuprofen", "given_at": _ago(2), "amount_mg": 180}]
        g = check_proposed_dose("ibuprofen", log, proposed_amount_mg=180, weight_kg=18, now=NOW)
        assert g.allowed is False
        assert g.too_early is True
        assert g.minutes_until_safe == 240  # 4h still to wait

    def test_redose_after_interval_allowed(self):
        # Same drug, last dose 7h ago (> 6h interval), well under the daily count -> allowed.
        log = [{"drug": "ibuprofen", "given_at": _ago(7), "amount_mg": 180}]
        g = check_proposed_dose("ibuprofen", log, proposed_amount_mg=180, weight_kg=18, now=NOW)
        assert g.allowed is True
        assert g.too_early is False


class TestDailyCapGuard:
    def test_exceeding_daily_count_blocked(self):
        # Acetaminophen allows 5 doses/24h; five already logged -> a sixth is blocked on count.
        log = [{"drug": "acetaminophen", "given_at": _ago(h), "amount_mg": 160}
               for h in (20, 16, 12, 8, 4)]
        g = check_proposed_dose("acetaminophen", log, proposed_amount_mg=160, weight_kg=10, now=NOW)
        assert g.allowed is False
        assert g.exceeds_daily_count is True
        assert g.doses_in_last_24h == 5

    def test_exceeding_daily_mg_blocked(self):
        # Count is fine, but the proposed milligrams would breach the 24h mg cap
        # (10 kg acetaminophen daily max = 750 mg; 500 already + 400 proposed = 900).
        log = [{"drug": "acetaminophen", "given_at": _ago(8), "amount_mg": 500}]
        g = check_proposed_dose("acetaminophen", log, proposed_amount_mg=400, weight_kg=10, now=NOW)
        assert g.allowed is False
        assert g.exceeds_daily_mg is True
        assert g.mg_in_last_24h == 500.0

class TestNextSafeDose:
    def test_countdown_after_recent_dose(self):
        # Ibuprofen 2h ago -> 4h (240 min) until the next safe dose, not due now.
        log = [{"drug": "ibuprofen", "given_at": _ago(2), "amount_mg": 180}]
        n = next_safe_dose("ibuprofen", log, now=NOW)
        assert n.is_due_now is False
        assert n.minutes_until_safe == 240
        assert n.interval_hours == 6

    def test_due_now_when_no_doses_logged(self):
        n = next_safe_dose("ibuprofen", [], now=NOW)
        assert n.is_due_now is True
        assert n.minutes_until_safe == 0
