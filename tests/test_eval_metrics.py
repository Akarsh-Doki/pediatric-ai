"""Tests for the RAG evaluation metrics (TIER 3, feature #7).

Known-answer cases for each metric so the math is pinned and reproducible offline.
Self-contained (no conftest) so it runs under repo pytest and the offline runner.
"""
from eval.metrics import (
    precision_at_k, recall_at_k, reciprocal_rank, mean_reciprocal_rank,
    grounding_score, hallucination_rate,
    calibration_buckets, expected_calibration_error,
)


class TestPrecisionRecall:
    def test_precision_at_k_partial(self):
        # top-3 = [A, X, B]; relevant = {A, B, C}; 2 of 3 are relevant.
        assert precision_at_k(["A", "X", "B", "Y"], {"A", "B", "C"}, k=3) == 2 / 3

    def test_precision_at_k_perfect(self):
        assert precision_at_k(["A", "B"], {"A", "B", "C"}, k=2) == 1.0

    def test_precision_at_k_zero_when_no_hits(self):
        assert precision_at_k(["X", "Y"], {"A"}, k=2) == 0.0

    def test_recall_at_k(self):
        # top-3 hits A and B out of relevant {A,B,C} -> 2/3.
        assert recall_at_k(["A", "X", "B", "Y"], {"A", "B", "C"}, k=3) == 2 / 3

    def test_recall_full_when_all_relevant_retrieved(self):
        assert recall_at_k(["A", "B", "C"], {"A", "B"}, k=3) == 1.0

    def test_recall_zero_with_no_relevant_defined(self):
        assert recall_at_k(["A"], set(), k=3) == 0.0


class TestMRR:
    def test_reciprocal_rank_first_position(self):
        assert reciprocal_rank(["A", "B"], {"A"}) == 1.0

    def test_reciprocal_rank_third_position(self):
        assert reciprocal_rank(["X", "Y", "A"], {"A"}) == 1 / 3

    def test_reciprocal_rank_none_found(self):
        assert reciprocal_rank(["X", "Y"], {"A"}) == 0.0

    def test_mean_reciprocal_rank(self):
        # ranks: 1 (rr=1) and 2 (rr=0.5) -> mean 0.75.
        cases = [(["A", "B"], {"A"}), (["X", "B"], {"B"})]
        assert mean_reciprocal_rank(cases) == 0.75


class TestGrounding:
    def test_fully_grounded_answer(self):
        ctx = ["Give fluids and rest. Fever usually resolves on its own in children."]
        ans = "Fever usually resolves on its own. Give fluids and rest."
        assert grounding_score(ans, ctx) == 1.0
        assert hallucination_rate(ans, ctx) == 0.0

    def test_ungrounded_sentence_detected(self):
        ctx = ["Acetaminophen can reduce fever in children."]
        # second sentence invents unrelated content not present in context.
        ans = "Acetaminophen reduces fever. The pyramids were built by aliens yesterday."
        score = grounding_score(ans, ctx)
        assert score == 0.5  # 1 of 2 sentences supported
        assert hallucination_rate(ans, ctx) == 0.5

    def test_noncontent_sentence_not_penalized(self):
        ctx = ["Ibuprofen helps with pain."]
        ans = "It is so."  # all tokens are stopwords / too short -> no checkable content
        assert grounding_score(ans, ctx) == 1.0


class TestCalibration:
    def test_buckets_count_and_accuracy(self):
        # two high-confidence correct, one high-confidence wrong -> top bucket acc 2/3.
        records = [(0.9, True), (0.95, True), (0.85, False)]
        buckets = calibration_buckets(records, n_buckets=5)
        top = buckets[-1]  # [0.8, 1.0]
        assert top["n"] == 3
        assert top["accuracy"] == round(2 / 3, 3)

    def test_perfect_calibration_zero_error(self):
        # confidence 1.0 always correct, confidence 0.0 always wrong -> ECE 0.
        records = [(1.0, True), (1.0, True), (0.0, False), (0.0, False)]
        assert expected_calibration_error(records, n_buckets=5) == 0.0

    def test_overconfidence_has_positive_error(self):
        # high confidence but frequently wrong -> nonzero ECE.
        records = [(0.9, False), (0.9, False), (0.9, True)]
        assert expected_calibration_error(records, n_buckets=5) > 0.0
