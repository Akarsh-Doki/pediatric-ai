import uuid # imports Python UUID library (Universally Unique Identifiers) create 128-bit random IDs, which are used to make unique identifiers globally
from datetime import datetime, timezone # imports datetime tools and ensures all timestamps are stored in UTC regardless where the server is ran

from sqlalchemy import (
    create_engine, Column, String, Integer, Float, Boolean, Text,
    DateTime, Date, ForeignKey,
) # Instead of using raw SQL, SQLALchemy allows us to write Python objects into sql, such as create_engine, which makes a connection pool to Postgres

from sqlalchemy.dialects.postgresql import UUID, JSONB # These are psql specific types. UUID stores the UUIDs nativley so it is faster to index. JSON stored JSON data in a binary format that is indexable, which is used for known_conditions and medications
from sqlalchemy.orm import declarative_base, sessionmaker, relationship # declarative_base makes a base class that all table classes inherit from, sessionmaker creates database sessions, and relationship defines how tables connect to each other in Python
from pgvector.sqlalchemy import Vector # Vector allows you to store 384 dimensional vectors for chunk embeddings, which is added using pgvector

from backend.config import get_settings # Loads your application configuration from .env using get_settings()

settings = get_settings() 

engine = create_engine(
    settings.database_url,
    pool_size=10, # keeps 10 connections open at all times, so when the API grabs a request, it grabs a connection from the pool instead of opening a new one
    max_overflow=20, # If all 10 are busy, it opens 20 more temporarily (max 30 connections)
    pool_pre_ping=True, # before using a connection from the pool, sends a tiny "are you alive?" query to PostgreSQL
) # This creates a database connection engine with a connection pool. This allows the API to handle multiple requests concurrently

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine) # This creates a session factory, so everytime you call SessionLocal(), you get a new database session. 
# autocommit=False makes it so changes don't save to the db until you explicitly call db.commit(), which allows you to use multiple operations into one transaction
# autoflush=False makes it so aqlalchemy won't automatically send pending change to the database before every query
# bind=engine # this factory uses the connection pool we defined earlier
Base = declarative_base() # Creates a base class for all the table models, so every class that inherits from this Base becomes its own class


def get_db(): # makes a new session. 
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def utcnow():
    return datetime.now(timezone.utc) # returns the current UTC


class Patient(Base): # Makes patient table in PostgreSQL. Makes ID for each patient, which is the primary key. Also includes name, age, sec, weight, etc.
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
    doses = relationship("Dose", back_populates="patient", order_by="Dose.given_at")


class GuidelineDoc(Base): # Stores the metadata about each PDF in the corpus, where each row is a PDF. 
    __tablename__ = "guideline_docs"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(500), nullable=False)
    source = Column(String(255), nullable=False)
    publication_date = Column(Date, nullable=True)
    category = Column(String(100), default="pediatric")
    file_path = Column(String(1000), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    chunks = relationship("Chunk", back_populates="document")


class Chunk(Base): # This is the table where RAG lives. Each row is a ~600 token piece of a PDF with its vector embedding. 600 tokens is the sweet spot where each chunk is focused enough to produce a precise embedding that matches relevant queries, but long enough to contain complete medical guidance (symptoms + treatment + when to worry) rather than disconnected fragments. Smaller chunks match too narrowly and miss context, larger chunks dilute the embedding across multiple topics and hurt retrieval accuracy. It also has a 100 token overlap
    __tablename__ = "chunks"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    doc_id = Column(UUID(as_uuid=True), ForeignKey("guideline_docs.id", ondelete="CASCADE"), nullable=False) # Acts as foreign key to the guidline doc table. ondelete="CASCADE" means that if you delete a document, all its chunks are automatically deleted too.
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(384))
    section_type = Column(String(100), nullable=True)
    age_range = Column(String(50), default="pediatric")
    condition_category = Column(String(100), nullable=True)
    page_num = Column(Integer, nullable=True)
    chunk_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    document = relationship("GuidelineDoc", back_populates="chunks")


class Conversation(Base): # Groups the messages into conversations
    __tablename__ = "conversations"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    started_at = Column(DateTime(timezone=True), default=utcnow)
    summary = Column(Text, nullable=True)
    patient = relationship("Patient", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", order_by="Message.created_at")


class Message(Base): # Every message from users and response is stored here
    __tablename__ = "messages"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id = Column(UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False) # Either "user" or "assistant"
    content = Column(Text, nullable=False)
    citations = Column(JSONB, default=[])
    confidence_score = Column(Float, nullable=True)
    refused = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    conversation = relationship("Conversation", back_populates="messages")
    symptom_extraction = relationship("SymptomExtraction", back_populates="message", uselist=False)


class SymptomExtraction(Base): # Stores the symptoms detected in each user message by the keyword extractor
    __tablename__ = "symptom_extractions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id = Column(UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    symptoms = Column(JSONB, default=[])
    severity_estimate = Column(String(20), default="unknown")
    extracted_at = Column(DateTime(timezone=True), default=utcnow)
    message = relationship("Message", back_populates="symptom_extraction")


class Event(Base): # An analytics/logging table. Every query creates an event with latency, token count, confidence, and more, which powers the /analytics/dashboard endpoint
    __tablename__ = "events"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(String(50), nullable=False)
    payload = Column(JSONB, default={}) # stores whatever metrics are relevant for this event type
    created_at = Column(DateTime(timezone=True), default=utcnow)

class Dose(Base):
    __tablename__ = "doses"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id", ondelete="CASCADE"), nullable=False)
    drug = Column(String(100), nullable=False)        # canonical ingredient, e.g. "acetaminophen"/"ibuprofen"
    amount_mg = Column(Float, nullable=True)           # mg given; nullable so you can log "a dose" without exact mg
    given_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)  # when it was given
    note = Column(String(500), nullable=True)          # optional free text
    created_at = Column(DateTime(timezone=True), default=utcnow)
    patient = relationship("Patient", back_populates="doses")