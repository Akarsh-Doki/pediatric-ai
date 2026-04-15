from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from backend.utils.logging_config import setup_logging
from backend.routers import patients, documents, chat, tts, analytics

logger = setup_logging()

app = FastAPI(
    title="PediatricAI",
    description="AI-powered pediatric health assistant with RAG",
    version="1.0.0",
)

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "https://d1c7nhfv15encr.cloudfront.net",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(patients.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(tts.router)
app.include_router(analytics.router)


@app.get("/health")
def health_check():
    return {"status": "healthy", "service": "pediatricai", "version": "1.0.0"}


@app.on_event("startup")
async def startup_event():
    logger.info("PediatricAI backend starting up...")
    from backend.utils.embeddings import get_embedding_model
    get_embedding_model()
    logger.info("PediatricAI backend ready")