import logging
import base64
import hashlib
import re
import edge_tts
import tempfile
import os

from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()

_tts_cache: dict[str, dict] = {}

# Medical terms to pause before for natural speech
PAUSE_BEFORE = [
    "however", "important", "warning", "note that", "keep in mind",
    "the good news", "call 911", "call poison control", "see a doctor",
    "see your pediatrician", "go to the er",
]


def _cache_key(text: str, voice: str) -> str:
    return hashlib.md5(f"{voice}:{text}".encode()).hexdigest()


def _add_ssml_pauses(text: str) -> str:
    """Insert pauses before key medical phrases for natural cadence."""
    for phrase in PAUSE_BEFORE:
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        text = pattern.sub(f"... {phrase}", text)
    return text


async def synthesize_speech(text: str, doctor_gender: str = "female") -> dict:
    voice = settings.tts_voice_female if doctor_gender == "female" else settings.tts_voice_male
    cache_key = _cache_key(text, voice)

    if cache_key in _tts_cache:
        logger.info("TTS cache hit")
        return _tts_cache[cache_key]

    # Add natural pauses
    text_with_pauses = _add_ssml_pauses(text)

    communicate = edge_tts.Communicate(
        text=text_with_pauses,
        voice=voice,
        rate=settings.tts_rate,
        pitch=settings.tts_pitch,
    )

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        await communicate.save(tmp_path)
        with open(tmp_path, "rb") as f:
            audio_bytes = f.read()

        audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
        result = {
            "audio_base64": audio_base64,
            "duration_ms": len(audio_bytes) // 16,
            "voice_used": voice,
        }
        _tts_cache[cache_key] = result
        logger.info(f"TTS generated: {len(audio_bytes)} bytes, voice={voice}")
        return result
    finally:
        os.unlink(tmp_path)