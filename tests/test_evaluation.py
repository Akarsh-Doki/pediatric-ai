"""
Tests for the evaluation service — the safety layer that decides
whether to refuse, warn, or proceed with a response.

WHY THIS MATTERS: If these thresholds are wrong, the system either
refuses everything (useless) or answers confidently with bad data
(dangerous). These tests verify the exact boundaries.
"""
import pytest
from backend.services.evaluation import should_refuse, compute_confidence, is_low_confidence


class TestShouldRefuse:
    """Tests for the hard refusal logic."""

    def test_refuses_when_no_chunks(self, mock_chunks_empty):
        """Empty retrieval = no relevant content at all. Must refuse."""
        assert should_refuse(mock_chunks_empty) is True

    def test_refuses_when_best_chunk_below_floor(self):
        """Best match is below 0.45 = essentially random noise."""
        garbage_chunks = [
            {"similarity": 0.30, "chunk_text": "irrelevant"},
            {"similarity": 0.25, "chunk_text": "also irrelevant"},
        ]
        assert should_refuse(garbage_chunks) is True

    def test_does_not_refuse_above_floor(self):
        """Best match at 0.50 is above the 0.45 floor — should NOT refuse."""
        ok_chunks = [
            {"similarity": 0.50, "chunk_text": "somewhat relevant"},
        ]
        assert should_refuse(ok_chunks) is False

    def test_does_not_refuse_high_similarity(self, mock_chunks_high):
        """High similarity chunks should never trigger refusal."""
        assert should_refuse(mock_chunks_high) is False

    def test_boundary_at_045(self):
        """Exactly 0.45 should NOT refuse (>= not >)."""
        boundary_chunks = [{"similarity": 0.45, "chunk_text": "boundary"}]
        assert should_refuse(boundary_chunks) is False

    def test_boundary_just_below_045(self):
        """0.449 should refuse."""
        below_chunks = [{"similarity": 0.449, "chunk_text": "just below"}]
        assert should_refuse(below_chunks) is True


class TestComputeConfidence:
    """Tests for the weighted confidence score."""

    def test_empty_chunks_returns_zero(self, mock_chunks_empty):
        """No chunks = zero confidence."""
        assert compute_confidence(mock_chunks_empty) == 0.0

    def test_high_similarity_chunks(self, mock_chunks_high):
        """High similarity chunks should produce confidence > 0.6."""
        confidence = compute_confidence(mock_chunks_high)
        assert confidence > 0.6
        assert confidence <= 1.0

    def test_weighted_formula(self):
        """Verify the 0.6*max + 0.4*avg formula."""
        chunks = [
            {"similarity": 0.80},
            {"similarity": 0.60},
        ]
        # max=0.80, avg=0.70
        # confidence = 0.6*0.80 + 0.4*0.70 = 0.48 + 0.28 = 0.76
        confidence = compute_confidence(chunks)
        assert confidence == 0.76

    def test_single_chunk(self):
        """Single chunk: max == avg, so confidence = similarity."""
        chunks = [{"similarity": 0.70}]
        confidence = compute_confidence(chunks)
        # 0.6*0.70 + 0.4*0.70 = 0.70
        assert confidence == 0.7

    def test_confidence_capped_at_one(self):
        """Confidence should never exceed 1.0."""
        perfect_chunks = [{"similarity": 1.0}, {"similarity": 1.0}]
        assert compute_confidence(perfect_chunks) <= 1.0


class TestIsLowConfidence:
    """Tests for the low-confidence warning logic."""

    def test_empty_chunks_is_low_confidence(self, mock_chunks_empty):
        assert is_low_confidence(mock_chunks_empty) is True

    def test_high_chunks_not_low_confidence(self, mock_chunks_high):
        """3 chunks above threshold = not low confidence."""
        assert is_low_confidence(mock_chunks_high) is False

    def test_single_good_chunk_is_low_confidence(self):
        """Only 1 chunk above threshold, but min_chunks_for_answer = 2."""
        one_good = [{"similarity": 0.70}]
        assert is_low_confidence(one_good) is True