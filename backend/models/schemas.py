from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

class PatientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    age: int = Field(..., ge=0, le=120)
    sex: str = Field(..., pattern="^(male|female)$")
    weight_kg: Optional[float] = Field(None, ge=0, le=300)
    known_conditions: list[str] = []
    medications: list[dict] = []

class PatientUpdate(BaseModel):
    name: Optional[str] = None
    age: Optional[int] = Field(None, ge=0, le=120)
    weight_kg: Optional[float] = Field(None, ge=0, le=300)
    known_conditions: Optional[list[str]] = None
    medications: Optional[list[dict]] = None

class PatientResponse(BaseModel):
    id: UUID
    name: str
    age: int
    sex: str
    weight_kg: Optional[float]
    known_conditions: list
    medications: list
    created_at: datetime

    class Config:
        from_attributes = True

class DocumentUploadResponse(BaseModel):
    document_id: UUID
    title: str
    status: str = "uploaded"


class IngestResponse(BaseModel):
    message: str
    document_id: UUID
    chunks_created: int = 0

class ChatRequest(BaseModel):
    patient_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: Optional[UUID] = None
    doctor_gender: str = Field(default="female", pattern="^(male|female)$")
    voice_enabled: bool = True

class CitationItem(BaseModel):
    doc_title: str
    source: str
    page_num: Optional[int]
    section_type: Optional[str]
    excerpt: str
    similarity_score: float

class ChatResponse(BaseModel):
    answer: str
    audio_base64: Optional[str] = None
    citations: list[CitationItem] = []
    confidence_score: float
    refused: bool
    latency_ms: int
    tokens_used: int = 0
    conversation_id: UUID
    urgency: str = "none"

class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    doctor_gender: str = Field(default="female", pattern="^(male|female)$")

class TTSResponse(BaseModel):
    audio_base64: str
    duration_ms: int = 0
    voice_used: str

class AnalyticsDashboard(BaseModel):
    total_queries: int
    avg_latency_ms: float
    refusal_rate: float
    top_symptoms: list[dict]
    queries_today: int

class MessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    citations: list
    confidence_score: Optional[float]
    refused: bool
    created_at: datetime

    class Config:
        from_attributes = True

class ConversationSummary(BaseModel):
    id: UUID
    started_at: datetime
    message_count: int
    last_message_preview: str

class ConversationHistory(BaseModel):
    conversation_id: UUID
    patient_name: str
    messages: list[MessageResponse]
    started_at: datetime