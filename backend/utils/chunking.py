import re
import logging
from transformers import AutoTokenizer
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()
_tokenizer = None


def get_tokenizer():
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(
            f"sentence-transformers/{settings.embedding_model}"
        )
    return _tokenizer


def count_tokens(text: str) -> int:
    tokenizer = get_tokenizer()
    return len(tokenizer.encode(text, add_special_tokens=False))


def chunk_text(text: str, chunk_size: int = None, chunk_overlap: int = None) -> list[str]:
    if chunk_size is None:
        chunk_size = settings.chunk_size
    if chunk_overlap is None:
        chunk_overlap = settings.chunk_overlap

    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = []
    current_chunk_sentences = []
    current_token_count = 0

    for sentence in sentences:
        sentence_tokens = count_tokens(sentence)

        if sentence_tokens > chunk_size:
            if current_chunk_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = []
                current_token_count = 0
            chunks.append(sentence)
            continue

        if current_token_count + sentence_tokens > chunk_size and current_chunk_sentences:
            chunks.append(" ".join(current_chunk_sentences))
            overlap_sentences = []
            overlap_tokens = 0
            for s in reversed(current_chunk_sentences):
                s_tokens = count_tokens(s)
                if overlap_tokens + s_tokens > chunk_overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_tokens += s_tokens
            current_chunk_sentences = overlap_sentences
            current_token_count = overlap_tokens

        current_chunk_sentences.append(sentence)
        current_token_count += sentence_tokens

    if current_chunk_sentences:
        chunks.append(" ".join(current_chunk_sentences))

    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks