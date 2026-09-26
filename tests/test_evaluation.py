import pytest
from backend.services.evaluation import should_refuse, compute_confidence, is_low_confidence


class TestShouldRefuse:
    """Tests for the hard refusal logic."""

    def test_refuses_when_no_chunks(self, mock_chunks_empty):
        """Empty retrieval = no relevant content at all. Must refuse."""
        assert should_refuse(mock_chunks_empty) is True

    def test_refuses_when_best_chunk_below_floor(self):
        """Best match is below the cutoff = essentially random noise."""
        garbage_chunks = [
            {"similarity": 0.30, "chunk_text": "irrelevant"},
            {"similarity": 0.25, "chunk_text": "also irrelevant"},
        ]
        assert should_refuse(garbage_chunks, threshold=0.45) is True

    def test_does_not_refuse_above_floor(self):
        """Best match at 0.50 is above a 0.45 cutoff — should NOT refuse."""
        ok_chunks = [
            {"similarity": 0.50, "chunk_text": "somewhat relevant"},
        ]
        assert should_refuse(ok_chunks, threshold=0.45) is False

    def test_does_not_refuse_high_similarity(self, mock_chunks_high):
        """High similarity chunks should never trigger refusal."""
        assert should_refuse(mock_chunks_high) is False

    def test_boundary_at_cutoff(self):
        """Exactly the cutoff should NOT refuse (>= not >)."""
        boundary_chunks = [{"similarity": 0.45, "chunk_text": "boundary"}]
        assert should_refuse(boundary_chunks, threshold=0.45) is False

    def test_boundary_just_below_cutoff(self):
        """Just below the cutoff should refuse."""
        below_chunks = [{"similarity": 0.449, "chunk_text": "just below"}]
        assert should_refuse(below_chunks, threshold=0.45) is True

    def test_default_cutoff_is_the_retrieval_setting(self):
        """With no threshold given, uses settings.similarity_threshold (same as retrieval)."""
        from backend.config import get_settings
        cutoff = get_settings().similarity_threshold
        assert should_refuse([{"similarity": cutoff, "chunk_text": "x"}]) is False
        assert should_refuse([{"similarity": cutoff - 0.001, "chunk_text": "x"}]) is True


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