"""
Hybrid (keyword + vector) retrieval  (TIER 3, feature #7 — optional upgrade).

The production retriever (backend/services/retrieval.py) is dense-only: it ranks chunks
purely by embedding cosine similarity. Dense retrieval can miss queries that hinge on a
rare exact token (a specific drug name, a dosage unit, a proper noun) where lexical
overlap is the stronger signal. This module adds a sparse TF-IDF lexical score and
fuses it with the dense score, then reorders — a cheap, no-download alternative to a
cross-encoder reranker (which would require fetching model weights).

Design
------
* The fusion math (normalization + weighted combine) is PURE and unit-tested.
* `tfidf_scores` uses scikit-learn (already a project dependency — no network/download).
* `hybrid_rerank` takes the candidate chunks the dense retriever already returned
  (each carrying its vector `similarity`) and re-scores them; it does not re-query the DB.
  run_eval.py compares dense-only vs. hybrid on the labeled test set to show the lift.
"""
from __future__ import annotations

from typing import Sequence


def min_max_normalize(scores: Sequence) -> list:
    """Scale scores to [0, 1]. Constant input -> all zeros (no signal to contribute)."""
    scores = list(scores)
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-12:
        return [0.0 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def combine_scores(vector_scores: Sequence, lexical_scores: Sequence, alpha: float = 0.6) -> list:
    """Weighted fusion of (normalized) dense and sparse scores.

    alpha is the dense weight: score = alpha*vector + (1-alpha)*lexical, after each side
    is min-max normalized so neither dominates by raw scale. alpha=1 -> dense-only;
    alpha=0 -> lexical-only.
    """
    if len(vector_scores) != len(lexical_scores):
        raise ValueError("vector_scores and lexical_scores must be the same length")
    v = min_max_normalize(vector_scores)
    l = min_max_normalize(lexical_scores)
    return [alpha * vi + (1 - alpha) * li for vi, li in zip(v, l)]


def tfidf_scores(query: str, documents: Sequence) -> list:
    """Cosine similarity between `query` and each document under a TF-IDF vectorizer fit
    on the documents + query. Returns one score per document (0 if no lexical overlap)."""
    documents = list(documents)
    if not documents:
        return []
    # Local import so importing this module never hard-requires sklearn until it's used.
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    vectorizer = TfidfVectorizer(stop_words="english")
    matrix = vectorizer.fit_transform(list(documents) + [query])
    doc_matrix = matrix[:-1]
    query_vec = matrix[-1]
    sims = cosine_similarity(query_vec, doc_matrix)[0]
    return [float(s) for s in sims]


def hybrid_rerank(query: str, chunks: Sequence, alpha: float = 0.6, top_k: int = None) -> list:
    """Re-rank dense-retrieved `chunks` by fusing their vector similarity with a TF-IDF
    lexical score over their text.

    chunks: list of dicts as returned by retrieval.search_chunks (must include
            'chunk_text' and 'similarity'). Returns a new list, ordered best-first, each
            chunk annotated with 'lexical_score' and 'hybrid_score'.
    """
    chunks = list(chunks)
    if not chunks:
        return []
    vector_scores = [c.get("similarity", 0.0) for c in chunks]
    lexical = tfidf_scores(query, [c.get("chunk_text", "") for c in chunks])
    fused = combine_scores(vector_scores, lexical, alpha=alpha)

    ranked = []
    for c, lex, hyb in zip(chunks, lexical, fused):
        nc = dict(c)
        nc["lexical_score"] = round(lex, 4)
        nc["hybrid_score"] = round(hyb, 4)
        ranked.append(nc)
    ranked.sort(key=lambda x: x["hybrid_score"], reverse=True)
    return ranked[:top_k] if top_k else ranked
