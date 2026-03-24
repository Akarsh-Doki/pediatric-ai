import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean, Text,
    DateTime, Date, ForeignKey,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from pgvector.sqlalchemy import Vector

from backend.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow():
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    age = Column(Integer, nullable=False)
    sex = Column(String(10), nullable=False)
    weight_kg = Column(Float, nullable=True)
    known_conditions = Column(JSONB, default=[])
    medications = Column(JSONB, default=[])
    created_at = Column(DateTime(timezone=True), default=utcnow)
    conversations = relationship("Conversation", back_populates="patient")


class GuidelineDoc(Base):
    __tablename__ = "guideline_docs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    source = Column(String(255), nullable=False)
    publication_date = Column(Date, nullable=True)
    category = Column(String(100), default="pediatric")
    file_path = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    chunks = relationship("Chunk", back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("guideline_docs.id", ondelete="CASCADE"), nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(384))
    section_type = Column(String(100), nullable=True)
    age_range = Column(String(50), default="pediatric")
    condition_category = Column(String(100), nullable=True)
    page_num = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    document = relationship("GuidelineDoc", back_populates="chunks")


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    summary = Column(Text, nullable=True)
    patient = relationship("Patient", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base):
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(JSONB, default=[])
    confidence_score = Column(Float, nullable=True)
    refused = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    conversation = relationship("Conversation", back_populates="messages")
    symptom_extraction = relationship("SymptomExtraction", back_populates="message", uselist=False)


class SymptomExtraction(Base):
    __tablename__ = "symptom_extractions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    symptoms = Column(JSONB, default=[])
    severity_estimate = Column(String(20), default="unknown")
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    message = relationship("Message", back_populates="symptom_extraction")


class Event(Base):
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), default=utcnow)