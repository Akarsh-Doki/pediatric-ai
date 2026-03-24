import logging
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()


def should_refuse(chunks: list[dict]) -> bool:
    if not chunks:
        return True
    good_chunks = [c for c in chunks if c.get("similarity", 0) >= settings.similarity_threshold]
    if len(good_chunks) < settings.min_chunks_for_answer:
        logger.info(f"Refusing: only {len(good_chunks)} chunks above threshold")
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