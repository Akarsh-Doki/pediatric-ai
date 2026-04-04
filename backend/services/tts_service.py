import logging
import base64
import hashlib
import tempfile
import os

from gtts import gTTS
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()

_tts_cache: dict[str, dict] = {}


def _cache_key(text: str, voice: str) -> str:
    return hashlib.md5(f"{voice}:{text}".encode()).hexdigest()


async def synthesize_speech(text: str, doctor_gender: str = "male") -> dict:
    voice = "en-GB-RyanNeural" if doctor_gender == "male" else "en-GB-SoniaNeural"
    cache_key = _cache_key(text, voice)

    if cache_key in _tts_cache:
        logger.info("TTS cache hit")
        return _tts_cache[cache_key]

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        tts = gTTS(text=text, lang="en", tld="co.uk")
        tts.save(tmp_path)

        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        result = {
            "audio_base64": audio_base64,
            "duration_ms": len(audio_bytes) // 16,
            "voice_used": "gTTS-en-co.uk",
        }
        _tts_cache[cache_key] = result
        logger.info(f"TTS generated: {len(audio_bytes)} bytes")
        return result
    finally:
        os.unlink(tmp_path)