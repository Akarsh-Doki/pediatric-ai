"""
RAG evaluation metrics  (TIER 3, feature #7).

Pure, dependency-free functions for measuring retrieval quality and answer grounding.
Nothing here touches the network, the DB, or the LLM, so every metric is unit-tested
deterministically. run_eval.py wires these to the live retriever to produce a real
before/after table; this module just defines the math.

Conventions
-----------
* "ids" are any hashable identifiers for retrieved/relevant items. In this project we
  evaluate at the *document-source* level (a question's gold answer lives in one or more
  source PDFs), but the functions are id-agnostic and work equally on chunk ids.
* Retrieved lists are RANK-ORDERED (best first). Order matters for MRR and @k cutoffs.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence


def precision_at_k(retrieved: Sequence, relevant: Iterable, k: int) -> float:
    """Of the top-k retrieved items, what fraction are relevant."""
    if k <= 0:
        return 0.0
    rel = set(relevant)
    top = list(retrieved)[:k]
    if not top:
        return 0.0
    hits = sum(1 for r in top if r in rel)
    return hits / len(top)


def recall_at_k(retrieved: Sequence, relevant: Iterable, k: int) -> float:
    """Of all relevant items, what fraction appear in the top-k retrieved."""
    rel = set(relevant)
    if not rel:
        return 0.0
    top = set(list(retrieved)[:k])
    return len(top & rel) / len(rel)


def reciprocal_rank(retrieved: Sequence, relevant: Iterable) -> float:
    """1 / rank of the first relevant item (rank starts at 1); 0 if none retrieved."""
    rel = set(relevant)
    for i, r in enumerate(retrieved, start=1):
        if r in rel:
            return 1.0 / i
    return 0.0


def mean_reciprocal_rank(cases: Iterable) -> float:
    """Mean of reciprocal_rank over (retrieved, relevant) pairs."""
    cases = list(cases)
    if not cases:
        return 0.0
    return sum(reciprocal_rank(ret, rel) for ret, rel in cases) / len(cases)


# --------------------------------------------------------------------------
# Grounding / hallucination
# --------------------------------------------------------------------------
_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "to", "of", "in", "on", "for", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those",
    "as", "at", "by", "from", "your", "you", "their", "they", "can", "may", "should",
    "will", "would", "about", "into", "out", "up", "do", "does", "not", "no", "yes",
    "child", "childs", "baby", "kid",
}


def _content_tokens(text: str) -> set:
    return {t for t in _WORD.findall((text or "").lower()) if t not in _STOP and len(t) > 2}


def _split_sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p.strip()]


def sentence_is_supported(sentence: str, context_tokens: set, threshold: float = 0.5) -> bool:
    """A sentence counts as supported if at least `threshold` of its content tokens
    appear somewhere in the retrieved context. Deterministic lexical proxy for grounding
    (no LLM judge), which is what makes it reproducible in an offline test."""
    toks = _content_tokens(sentence)
    if not toks:
        return True  # no checkable content tokens (e.g. all stopwords) — don't penalize
    overlap = len(toks & context_tokens) / len(toks)
    return overlap >= threshold


def grounding_score(answer: str, contexts: Iterable, threshold: float = 0.5) -> float:
    """Fraction of the answer's sentences supported by the retrieved contexts.
    contexts: iterable of chunk texts the answer was generated from."""
    ctx_tokens: set = set()
    for c in contexts:
        ctx_tokens |= _content_tokens(c)
    sentences = _split_sentences(answer)
    if not sentences:
        return 1.0
    supported = sum(1 for s in sentences if sentence_is_supported(s, ctx_tokens, threshold))
    return supported / len(sentences)


def hallucination_rate(answer: str, contexts: Iterable, threshold: float = 0.5) -> float:
    """1 - grounding_score: fraction of answer sentences NOT supported by context."""
    return 1.0 - grounding_score(answer, contexts, threshold)


# --------------------------------------------------------------------------
# Abstention / calibration
# --------------------------------------------------------------------------
def calibration_buckets(records: Iterable, n_buckets: int = 5) -> list:
    """Group (confidence, was_correct) records into equal-width confidence buckets and
    report mean confidence vs. observed accuracy per bucket. A well-calibrated system has
    mean_confidence ≈ accuracy in every bucket.

    records: iterable of (confidence: float in [0,1], was_correct: bool)
    returns: list of dicts {range, n, mean_confidence, accuracy}
    """
    records = [(float(c), bool(ok)) for c, ok in records]
    out = []
    width = 1.0 / n_buckets
    for b in range(n_buckets):
        lo, hi = b * width, (b + 1) * width
        # include the right edge in the last bucket
        in_b = [(c, ok) for c, ok in records if (lo <= c < hi) or (b == n_buckets - 1 and c == hi)]
        if not in_b:
            out.append({"range": (round(lo, 3), round(hi, 3)), "n": 0,
                        "mean_confidence": None, "accuracy": None})
            continue
        mc = sum(c for c, _ in in_b) / len(in_b)
        acc = sum(1 for _, ok in in_b if ok) / len(in_b)
        out.append({"range": (round(lo, 3), round(hi, 3)), "n": len(in_b),
                    "mean_confidence": round(mc, 3), "accuracy": round(acc, 3)})
    return out


def expected_calibration_error(records: Iterable, n_buckets: int = 5) -> float:
    """ECE: sample-weighted average gap between confidence and accuracy across buckets."""
    records = [(float(c), bool(ok)) for c, ok in records]
    total = len(records)
    if total == 0:
        return 0.0
    ece = 0.0
    for bucket in calibration_buckets(records, n_buckets):
        if bucket["n"] == 0:
            continue
        ece += (bucket["n"] / total) * abs(bucket["mean_confidence"] - bucket["accuracy"])
    return round(ece, 4)
