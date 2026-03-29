import logging
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()


def should_refuse(chunks: list[dict]) -> bool:
    """Only refuse if truly nothing relevant was found."""
    if not chunks:
        return True
    # Check if ANY chunk is above a minimum threshold (lower than the confidence threshold)
    best_sim = max(c.get("similarity", 0) for c in chunks)
    if best_sim < 0.45:
        logger.info(f"Refusing: best similarity {best_sim:.3f} below minimum 0.45")
        return True
    return False


def compute_confidence(chunks: list[dict]) -> float:
    if not chunks:
        return 0.0
    similarities = [c.get("similarity", 0) for c in chunks]
    avg_sim = sum(similarities) / len(similarities)
    max_sim = max(similarities)
    confidence = 0.6 * max_sim + 0.4 * avg_sim
    return round(min(confidence, 1.0), 3)


def is_low_confidence(chunks: list[dict]) -> bool:
    """Check if we have chunks but they're borderline quality."""
    if not chunks:
        return True
    good_chunks = [c for c in chunks if c.get("similarity", 0) >= settings.similarity_threshold]
    return len(good_chunks) < settings.min_chunks_for_answer

