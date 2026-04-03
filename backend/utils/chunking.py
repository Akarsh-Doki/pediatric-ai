import re # re for regex-based sentence splitting
import logging
from transformers import AutoTokenizer # AutoTokenizer from HuggingFace loads the exact same tokenizer the embedding model uses.
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()
_tokenizer = None # variable to cache the tokenizer


def get_tokenizer(): # Loads the tokenizer on first use
    global _tokenizer
    if _tokenizer is None:
        _tokenizer = AutoTokenizer.from_pretrained(
            f"sentence-transformers/{settings.embedding_model}"
        ) # This downloads and loads the tokenizer configuration
    return _tokenizer


def count_tokens(text: str) -> int:
    tokenizer = get_tokenizer() # Counts how many tokens a text string contains and removes CLS and SEP
    return len(tokenizer.encode(text, add_special_tokens=False))


def chunk_text(text: str, chunk_size: int = None, chunk_overlap: int = None) -> list[str]:
    if chunk_size is None: #  # Defaults to configured values (600 and 100)
        chunk_size = settings.chunk_size
    if chunk_overlap is None:
        chunk_overlap = settings.chunk_overlap

    sentences = re.split(r'(?<=[.!?])\s+', text) # Used to meaningfully split sentences
    sentences = [s.strip() for s in sentences if s.strip()]

    chunks = [] # Initializes the chunking state
    current_chunk_sentences = []
    current_token_count = 0

    for sentence in sentences: # Counts the number of tokens in each sentence
        sentence_tokens = count_tokens(sentence)

        if sentence_tokens > chunk_size: # Edge case: a single sentence longer than 600 tokens
            if current_chunk_sentences:
                chunks.append(" ".join(current_chunk_sentences))
                current_chunk_sentences = []
                current_token_count = 0
            chunks.append(sentence)
            continue

        if current_token_count + sentence_tokens > chunk_size and current_chunk_sentences: # Makes the Chunk boundary
            chunks.append(" ".join(current_chunk_sentences))
            overlap_sentences = [] # The overlap mechanism. After flushing a chunk, don't start the next chunk empty — carry over the last ~100 tokens worth of sentences. 
            overlap_tokens = 0
            for s in reversed(current_chunk_sentences):
                s_tokens = count_tokens(s)
                if overlap_tokens + s_tokens > chunk_overlap:
                    break
                overlap_sentences.insert(0, s)
                overlap_tokens += s_tokens
            current_chunk_sentences = overlap_sentences
            current_token_count = overlap_tokens

        current_chunk_sentences.append(sentence) # Add the current sentence to the in-progress chunk.
        current_token_count += sentence_tokens

    if current_chunk_sentences:
        chunks.append(" ".join(current_chunk_sentences))

    logger.info(f"Split text into {len(chunks)} chunks")
    return chunks