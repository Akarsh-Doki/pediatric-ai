import logging
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()


def should_refuse(chunks: list[dict], threshold: float = None) -> bool: # If retrieval returned zero chunks
    """Refuse if no chunk reaches the similarity cutoff. Uses the same cutoff as retrieval
    (settings.similarity_threshold), so there is one number to tune, not two."""
    if threshold is None:
        threshold = settings.similarity_threshold
    if not chunks:
        return True
    best_sim = max(c.get("similarity", 0) for c in chunks)
    if best_sim < threshold:
        logger.info(f"Refusing: best similarity {best_sim:.3f} below cutoff {threshold}")
        return True
    return False


def compute_confidence(chunks: list[dict]) -> float: # This is Weighted confidence score. Why weighted toward the best match? Because one highly relevant chunk is more useful than five mediocre ones.
    if not chunks:
        return 0.0
    similarities = [c.get("similarity", 0) for c in chunks]
    avg_sim = sum(similarities) / len(similarities)
    max_sim = max(similarities)
    confidence = 0.6 * max_sim + 0.4 * avg_sim
    return round(min(confidence, 1.0), 3)


def is_low_confidence(chunks: list[dict]) -> bool: # Checks if enough high-quality chunks were found
    """Check if we have chunks but they're borderline quality."""
    if not chunks:
        return True
    good_chunks = [c for c in chunks if c.get("similarity", 0) >= settings.similarity_threshold]
    return len(good_chunks) < settings.min_chunks_for_answer

