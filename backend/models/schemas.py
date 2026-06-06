from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID

class PatientCreate(BaseModel): # The schema for making a new patient (POST /patients)
    name: str = Field(..., min_length=1, max_length=255)
    age: int = Field(..., ge=0, le=120) # ... means that this field is required
    sex: str = Field(..., pattern="^(male|female)$")
    weight_kg: Optional[float] = Field(None, ge=0, le=300)
    known_conditions: list[str] = []
    medications: list[dict] = []

class PatientUpdate(BaseModel): # Schema for updating a patient (PATCH /patients/{id}). Every field is optional in case you want to update only one field
    name: Optional[str] = None
    age: Optional[int] = Field(None, ge=0, le=120)
    weight_kg: Optional[float] = Field(None, ge=0, le=300)
    known_conditions: Optional[list[str]] = None
    medications: Optional[list[dict]] = None

class PatientResponse(BaseModel): # The schema for what comes back from the API. from_attributes = True tells Pydantic: "you can create this schema from a SQLAlchemy object, not just a dictionary." 
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

class DocumentUploadResponse(BaseModel): # Returned after uploading a PDF, and tells the frontend "here's the document ID, and its status is uploaded"
    document_id: UUID
    title: str
    status: str = "uploaded"


class IngestResponse(BaseModel): # returned after ingestion, and tells you how many chunks were generated from the document
    message: str
    document_id: UUID
    chunks_created: int = 0

class ChatRequest(BaseModel): # This is what the frontend sends when a user asks a question
    patient_id: UUID
    message: str = Field(..., min_length=1, max_length=5000)
    conversation_id: Optional[UUID] = None
    doctor_gender: str = Field(default="female", pattern="^(male|female)$")
    voice_enabled: bool = True

class CitationItem(BaseModel): # One citation, shown in the UI under each response 
    doc_title: str
    source: str
    page_num: Optional[int]
    section_type: Optional[str]
    excerpt: str
    similarity_score: float

class ChatResponse(BaseModel): # This is everything that comes back from a chat query
    answer: str
    audio_base64: Optional[str] = None
    citations: list[CitationItem] = []
    confidence_score: float
    refused: bool
    latency_ms: int
    tokens_used: int = 0
    conversation_id: UUID
    urgency: str = "none"
    medication_warnings: list[dict] = []

class TTSRequest(BaseModel): # Input for text-to-speech synthesis
    text: str = Field(..., min_length=1, max_length=10000)
    doctor_gender: str = Field(default="female", pattern="^(male|female)$")

class TTSResponse(BaseModel): # Returns the audio as a base64-encoded string
    audio_base64: str
    duration_ms: int = 0
    voice_used: str

class AnalyticsDashboard(BaseModel): # Powers the admin dashboard. Shows system health metrics.
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

class ConversationSummary(BaseModel): # Used in the sidebar to show past conversations
    id: UUID
    started_at: datetime
    message_count: int
    last_message_preview: str

class ConversationHistory(BaseModel): # The full conversation history with all message
    conversation_id: UUID
    patient_name: str
    messages: list[MessageResponse]
    started_at: datetime

# Medication feature schemas (#1 safety, #2 dose calc, #3 dose log) — all numbers come from deterministic services, never the LLM.

class DoseCalcRequest(BaseModel):  # input to the dose calculator (#2); needs weight_kg or weight_lb or it refuses
    drug: str = Field(..., min_length=1, max_length=100)   # "acetaminophen"/"ibuprofen" or a brand it can normalize
    weight_kg: Optional[float] = Field(None, gt=0, le=300)
    weight_lb: Optional[float] = Field(None, gt=0, le=660)
    age_months: Optional[int] = Field(None, ge=0, le=1200)
    age_years: Optional[float] = Field(None, ge=0, le=120)
    known_conditions: list[str] = []

class DoseCalcResponse(BaseModel):  # ok=False means it refused (unsupported drug, no weight, age floor) — read `reasons`
    drug: str
    ok: bool
    status: str
    display_name: str
    single_dose_mg: float
    single_dose_mg_range: list
    single_dose_ml: float
    concentration_label: str
    interval_hours: Optional[int]
    interval_display: str
    max_doses_per_24h: Optional[int]
    max_mg_per_24h: float
    weight_kg: float
    age_months: Optional[int]
    reasons: list
    warnings: list
    disclaimer: str

class MedSafetyRequest(BaseModel):  # input to the safety layer (#1); nothing here goes to the LLM
    drug: str = Field(..., min_length=1, max_length=200)
    age: Optional[int] = Field(None, ge=0, le=120)
    age_years: Optional[float] = Field(None, ge=0, le=120)
    known_conditions: list[str] = []
    medications: list[dict] = []

class MedSafetyResponse(BaseModel):  # blocked=True => do not give without pediatrician approval
    drug: str
    ingredients: list
    safe: bool
    blocked: bool
    max_severity: str
    warnings: list
    checked_against: dict

class DoseCreate(BaseModel):  # log a dose that was given (#3); given_at defaults to now if omitted
    drug: str = Field(..., min_length=1, max_length=100)
    amount_mg: Optional[float] = Field(None, ge=0, le=10000)
    given_at: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=500)

class DoseResponse(BaseModel):  # a single logged dose row
    id: UUID
    patient_id: UUID
    drug: str
    amount_mg: Optional[float]
    given_at: datetime
    note: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

class NextDoseResponse(BaseModel):  # when/whether the next dose of `drug` is safe
    drug: str
    last_dose_at: Optional[str]
    next_safe_at: Optional[str]
    minutes_until_safe: int
    is_due_now: bool
    interval_hours: Optional[int]

class DoseGuardRequest(BaseModel):  # ask the guard if giving `drug` now is safe given logged doses (#3)
    drug: str = Field(..., min_length=1, max_length=100)
    proposed_amount_mg: Optional[float] = Field(None, ge=0, le=10000)
    weight_kg: Optional[float] = Field(None, gt=0, le=300)

class DoseGuardResponse(BaseModel):  # allowed=False => too early or would breach the 24h cap
    drug: str
    allowed: bool
    too_early: bool
    exceeds_daily_count: bool
    exceeds_daily_mg: bool
    next_safe_at: Optional[str]
    minutes_until_safe: int
    doses_in_last_24h: int
    mg_in_last_24h: float
    warnings: list