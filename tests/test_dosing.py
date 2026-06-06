"""Tests for the deterministic OTC dose calculator (TIER 1, feature #2).

Exhaustive by design: this module outputs safety-critical numbers, so we test the
boundaries, the hard caps, every age floor, the missing-weight refusal, and that
aspirin / any non-OTC-antipyretic is never dosed.
"""
try:
    import pytest  # noqa: F401
    _approx = pytest.approx
except ImportError:  # offline stdlib runner fallback
    class _Approx:
        def __init__(self, val, abs=1e-6):
            self.val, self.abs = val, abs
        def __eq__(self, other):
            return abs(other - self.val) <= self.abs

    def _approx(val, abs=1e-6):
        return _Approx(val, abs=abs)

from backend.services.dosing import (
    compute_dose, lb_to_kg, normalize_drug_name, dose_interval_hours,
    daily_limits, supported_drugs,
)

class TestSupportedScope:
    def test_only_two_drugs_supported(self):
        assert set(supported_drugs()) == {"acetaminophen", "ibuprofen"}

    def test_aspirin_is_refused(self):
        r = compute_dose("aspirin", weight_kg=20, age_years=6)
        assert r.ok is False and r.status == "refused"
        assert "Reye" in " ".join(r.reasons)

    def test_aspirin_synonyms_refused(self):
        for name in ["asa", "Bayer", "acetylsalicylic acid"]:
            assert compute_dose(name, weight_kg=20, age_years=6).ok is False

    def test_unknown_drug_refused(self):
        r = compute_dose("amoxicillin", weight_kg=20, age_years=6)
        assert r.ok is False
        assert "only provides doses for acetaminophen" in " ".join(r.reasons)

    def test_prescription_drug_not_offered(self):
        assert compute_dose("prednisone", weight_kg=20, age_years=6).ok is False

class TestWeightRequired:
    def test_missing_weight_refused(self):
        r = compute_dose("acetaminophen", age_years=3)
        assert r.ok is False
        assert "weight is required" in " ".join(r.reasons)

    def test_zero_weight_refused(self):
        assert compute_dose("ibuprofen", weight_kg=0, age_years=3).ok is False

    def test_implausible_weight_refused(self):
        assert compute_dose("acetaminophen", weight_kg=200, age_years=10).ok is False

    def test_lb_input_converts(self):
        r = compute_dose("acetaminophen", weight_lb=22, age_months=12)
        assert r.ok is True
        # 22 lb = 9.979 kg; 15 mg/kg ~= 149.7 -> rounds to 150 mg
        assert r.single_dose_mg == 150.0

class TestAgeFloors:
    def test_ibuprofen_under_6_months_refused(self):
        r = compute_dose("ibuprofen", weight_kg=6, age_months=4)
        assert r.ok is False
        assert "under 6 months" in " ".join(r.reasons)

    def test_ibuprofen_exactly_6_months_allowed(self):
        assert compute_dose("ibuprofen", weight_kg=7, age_months=6).ok is True

    def test_acetaminophen_under_3_months_deferred(self):
        r = compute_dose("acetaminophen", weight_kg=5, age_months=2)
        assert r.ok is False
        assert "3 months" in " ".join(r.reasons)

    def test_acetaminophen_3_months_allowed(self):
        assert compute_dose("acetaminophen", weight_kg=6, age_months=3).ok is True

    def test_unknown_age_still_doses_with_caution(self):
        r = compute_dose("ibuprofen", weight_kg=12)  # no age
        assert r.ok is True
        assert any("6 months" in w for w in r.warnings)

class TestDoseMath:
    def test_acetaminophen_standard_dose(self):
        # 10 kg * 15 mg/kg = 150 mg
        r = compute_dose("acetaminophen", weight_kg=10, age_years=1)
        assert r.single_dose_mg == 150.0
        assert r.single_dose_mg_range == [100.0, 150.0]  # 10-15 mg/kg
        assert r.interval_hours == 4

    def test_ibuprofen_standard_dose(self):
        # 20 kg * 10 mg/kg = 200 mg
        r = compute_dose("ibuprofen", weight_kg=20, age_years=6)
        assert r.single_dose_mg == 200.0
        assert r.interval_hours == 6

    def test_ml_conversion_acetaminophen(self):
        # 150 mg at 160 mg/5 mL = 4.6875 mL -> rounds to nearest 0.5 = 4.5
        r = compute_dose("acetaminophen", weight_kg=10, age_years=1)
        assert r.single_dose_ml == 4.5

    def test_ml_conversion_ibuprofen(self):
        # 200 mg at 100 mg/5 mL = 10 mL
        r = compute_dose("ibuprofen", weight_kg=20, age_years=6)
        assert r.single_dose_ml == 10.0

    def test_brand_names_normalize(self):
        assert compute_dose("Tylenol", weight_kg=10, age_years=1).drug == "acetaminophen"
        assert compute_dose("Motrin", weight_kg=10, age_years=1).drug == "ibuprofen"
        assert compute_dose("children's advil", weight_kg=10, age_years=1).drug == "ibuprofen"


class TestHardCaps:
    def test_acetaminophen_single_dose_capped_at_1000(self):
        # 80 kg * 15 = 1200 -> capped at 1000 mg
        r = compute_dose("acetaminophen", weight_kg=80, age_years=14)
        assert r.single_dose_mg == 1000.0

    def test_ibuprofen_single_dose_capped_at_400(self):
        # 50 kg * 10 = 500 -> capped at 400 mg
        r = compute_dose("ibuprofen", weight_kg=50, age_years=13)
        assert r.single_dose_mg == 400.0

    def test_daily_cap_never_exceeds_absolute(self):
        # very heavy: per-kg daily would exceed absolute ceiling
        r = compute_dose("acetaminophen", weight_kg=120, age_years=16)
        assert r.ok is False or r.max_mg_per_24h <= 4000.0

    def test_daily_cap_weight_based_for_small_child(self):
        # 10 kg acetaminophen: 75 mg/kg/day = 750 mg, below the 4000 mg absolute cap.
        # Daily caps are NOT rounded to the dose increment (only single doses are).
        r = compute_dose("acetaminophen", weight_kg=10, age_years=1)
        assert r.max_mg_per_24h == 750.0

    def test_rounding_never_pushes_over_cap(self):
        r = compute_dose("ibuprofen", weight_kg=39.9, age_years=12)  # 399 mg, near cap
        assert r.single_dose_mg <= 400.0


class TestConditionFlags:
    def test_liver_disease_defers_acetaminophen(self):
        r = compute_dose("acetaminophen", weight_kg=20, age_years=6,
                         known_conditions=["chronic liver disease"])
        assert r.ok is False
        assert "liver" in " ".join(r.reasons).lower()

    def test_kidney_disease_defers_ibuprofen(self):
        r = compute_dose("ibuprofen", weight_kg=20, age_years=6,
                         known_conditions=["kidney disease"])
        assert r.ok is False

    def test_asthma_warns_but_doses_ibuprofen(self):
        r = compute_dose("ibuprofen", weight_kg=20, age_years=6,
                         known_conditions=["asthma"])
        assert r.ok is True
        assert any("asthma" in w.lower() or "wheezing" in w.lower() for w in r.warnings)


class TestDisclaimerAndHelpers:
    def test_result_always_has_disclaimer(self):
        assert compute_dose("acetaminophen", weight_kg=10, age_years=1).disclaimer
        assert compute_dose("aspirin", weight_kg=10, age_years=1).disclaimer

    def test_intervals_helper(self):
        assert dose_interval_hours("tylenol") == 4
        assert dose_interval_hours("advil") == 6
        assert dose_interval_hours("aspirin") is None

    def test_daily_limits_helper(self):
        # ibuprofen 18 kg: 40 mg/kg/day = 720 mg, below the 1200 mg absolute cap.
        lim = daily_limits("ibuprofen", weight_kg=18)
        assert lim["max_doses_per_24h"] == 4
        assert lim["max_mg_per_24h"] == 720.0
        # 20 kg would be 40*20 = 800 mg (still below the 1200 mg absolute cap).
        assert daily_limits("ibuprofen", weight_kg=20)["max_mg_per_24h"] == 800.0

    def test_lb_to_kg(self):
        assert lb_to_kg(22) == _approx(9.979, abs=0.01)

    def test_normalize_unknown_returns_none(self):
        assert normalize_drug_name("zzzpotion") is None
