"""Tests for hybrid (keyword + vector) retrieval (TIER 3, feature #7).

The fusion math is pinned with known-answer cases; the end-to-end rerank test shows the
intended behavior — a lexically-exact match that dense retrieval under-ranked gets
promoted. Uses scikit-learn (a project dependency), so it runs offline with no download.
Self-contained for both repo pytest and the offline runner.
"""
from eval.hybrid_retrieval import (
    min_max_normalize, combine_scores, tfidf_scores, hybrid_rerank,
)


class TestNormalization:
    def test_min_max_spread(self):
        assert min_max_normalize([0.5, 0.7, 0.6]) == [0.0, 1.0, 0.5]

    def test_constant_input_is_zeroed(self):
        # No spread -> no signal to contribute to fusion.
        assert min_max_normalize([0.4, 0.4, 0.4]) == [0.0, 0.0, 0.0]

    def test_empty(self):
        assert min_max_normalize([]) == []


class TestCombine:
    def test_alpha_one_is_dense_only(self):
        # Pure dense: result equals normalized vector scores, lexical ignored.
        out = combine_scores([0.2, 0.9, 0.5], [1.0, 0.0, 0.0], alpha=1.0)
        assert out == min_max_normalize([0.2, 0.9, 0.5])

    def test_alpha_zero_is_lexical_only(self):
        out = combine_scores([1.0, 0.0, 0.0], [0.2, 0.9, 0.5], alpha=0.0)
        assert out == min_max_normalize([0.2, 0.9, 0.5])

    def test_length_mismatch_raises(self):
        try:
            combine_scores([0.1, 0.2], [0.1], alpha=0.5)
            assert False, "expected ValueError"
        except ValueError:
            pass


class TestTfidf:
    def test_lexical_match_scores_highest(self):
        docs = [
            "ibuprofen dosing for fever in children",
            "eczema moisturizer and bathing routine",
            "when to call the doctor about a rash",
        ]
        scores = tfidf_scores("ibuprofen fever dose", docs)
        assert scores[0] == max(scores)
        assert scores[0] > 0.0
        # unrelated docs share no content terms with the query
        assert scores[1] == 0.0 and scores[2] == 0.0

    def test_empty_docs(self):
        assert tfidf_scores("anything", []) == []


class TestHybridRerank:
    def test_lexical_exact_match_promoted_over_dense_top(self):
        docs = [
            "eczema moisturizer and bathing routine",       # dense-favored but off-topic
            "ibuprofen dosing for fever in children",        # the lexically correct answer
            "when to call the doctor about a rash",
        ]
        chunks = [
            {"id": "eczema", "chunk_text": docs[0], "similarity": 0.82},
            {"id": "ibuprofen", "chunk_text": docs[1], "similarity": 0.78},
            {"id": "rash", "chunk_text": docs[2], "similarity": 0.70},
        ]
        reranked = hybrid_rerank("ibuprofen fever dose", chunks, alpha=0.5)
        assert reranked[0]["id"] == "ibuprofen"  # promoted from rank 2 to rank 1
        assert "hybrid_score" in reranked[0] and "lexical_score" in reranked[0]

    def test_empty_input(self):
        assert hybrid_rerank("q", []) == []

    def test_top_k_truncates(self):
        chunks = [
            {"id": "a", "chunk_text": "fever ibuprofen", "similarity": 0.9},
            {"id": "b", "chunk_text": "rash cream", "similarity": 0.8},
            {"id": "c", "chunk_text": "cough syrup", "similarity": 0.7},
        ]
        assert len(hybrid_rerank("fever", chunks, top_k=2)) == 2
