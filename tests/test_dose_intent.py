"""Tests for the chat -> dose-calculator bridge (TIER 1 #2)."""
from backend.services.dose_intent import (
    parse_dose_request, format_dose_answer, need_weight_message, format_safety_block,
)
from backend.services.dosing import compute_dose


class TestIntentDetection:
    def test_how_much_with_lb_and_age(self):
        req = parse_dose_request("how much ibuprofen for my 40 lb 5 year old?", {})
        assert req is not None
        assert req["drug"] == "ibuprofen"
        assert abs(req["weight_kg"] - 18.14) < 0.25
        assert req["age_years"] == 5.0

    def test_calculate_phrasing_with_brand(self):
        req = parse_dose_request("calculate how much tylenol to give", {"weight_kg": 10, "age": 1})
        assert req and req["drug"] == "acetaminophen"
        assert req["weight_kg"] == 10
        assert req["age_years"] == 1.0

    def test_what_dose_phrasing(self):
        req = parse_dose_request("what dose of ibuprofen?", {"weight_kg": 20, "age": 6})
        assert req and req["drug"] == "ibuprofen"

    def test_safety_question_not_a_calc_request(self):
        # "can I give ...?" with no quantity intent -> let RAG + safety handle it
        assert parse_dose_request("can I give my child ibuprofen?", {}) is None

    def test_non_drug_question_ignored(self):
        assert parse_dose_request("how much should my toddler sleep?", {}) is None

    def test_kg_weight_parsed(self):
        req = parse_dose_request("how many ml of ibuprofen for an 18 kg child", {})
        assert req["weight_kg"] == 18.0

    def test_age_in_months_parsed(self):
        req = parse_dose_request("how much acetaminophen for my 3 month old?", {})
        assert req["age_months"] == 3 and req["age_years"] is None

    def test_weight_falls_back_to_patient_record(self):
        req = parse_dose_request("what dose of ibuprofen?", {"weight_kg": 22, "age": 7})
        assert req["weight_kg"] == 22

    def test_missing_weight_is_none(self):
        req = parse_dose_request("how much ibuprofen for my 5 year old?", {})
        assert req is not None and req["weight_kg"] is None


class TestAnswerFormatting:
    def test_happy_dose_answer_has_mg_and_cap(self):
        r = compute_dose("ibuprofen", weight_kg=18, age_years=5)
        text = format_dose_answer(r, "Sam")
        assert "ibuprofen" in text.lower()
        assert "mg" in text
        assert "24 hours" in text

    def test_aspirin_refusal_surfaces_reye(self):
        r = compute_dose("aspirin", weight_kg=18, age_years=5)
        assert "Reye" in format_dose_answer(r)

    def test_age_floor_refusal_surfaces_reason(self):
        r = compute_dose("ibuprofen", weight_kg=6, age_months=3)
        text = format_dose_answer(r)
        assert not r.ok and len(text) > 0

    def test_need_weight_mentions_weight(self):
        assert "weight" in need_weight_message("ibuprofen").lower()

    def test_safety_block_includes_reason_and_defers(self):
        payloads = [{"warnings": [{"severity": "block", "message": "ALLERGY CONFLICT: amoxicillin."}]}]
        text = format_safety_block(payloads)
        assert "ALLERGY CONFLICT" in text and "pediatrician" in text.lower()
