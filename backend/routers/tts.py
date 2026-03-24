from fastapi import APIRouter
from backend.models.schemas import TTSRequest, TTSResponse
from backend.services.tts_service import synthesize_speech

router = APIRouter(prefix="/tts", tags=["tts"])


@router.post("/synthesize", response_model=TTSResponse)
async def synthesize(request: TTSRequest):
    result = await synthesize_speech(request.text, request.doctor_gender)
    return TTSResponse(**result)