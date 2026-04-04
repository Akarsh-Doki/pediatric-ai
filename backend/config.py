from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://pediatricai:pediatricai_dev_2024@localhost:5432/pediatricai" # The PostgreSQL connection string
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"

    # OpenAI (production)
    openai_api_key: str = ""
    llm_provider: str = "ollama"  # "ollama" or "openai"

    # Embeddings
    embedding_model: str = "all-MiniLM-L6-v2" # The SentenceTransformer model name and its output dimensionality. These must match — all-MiniLM-L6-v2 always produces 384-dimensional vectors.
    embedding_dimensions: int = 384

    # TTS
    tts_voice_female: str = "en-GB-SoniaNeural"
    tts_voice_male: str = "en-GB-RyanNeural"
    tts_rate: str = "-10%"
    tts_pitch: str = "-5Hz"

    # RAG
    retrieval_top_k: int = 10
    similarity_threshold: float = 0.55
    min_chunks_for_answer: int = 2
    chunk_size: int = 600
    chunk_overlap: int = 100

    # File storage
    upload_dir: str = "./data/guidelines"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()