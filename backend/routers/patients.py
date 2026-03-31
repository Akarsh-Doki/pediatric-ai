import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException # APIRouter allows you to make a group of related endpoints, and depends tells FastAPI: "before running this function, call get_db(), get the database session it yields, and pass it as the db parameter"
from sqlalchemy.orm import Session # Type hint for the database session

from backend.models.database import get_db, Patient, Conversation, Message # Imports the session dependency and the SQLAlchemy table models.
from backend.models.schemas import PatientCreate, PatientUpdate, PatientResponse, ConversationSummary

logger = logging.getLogger("pediatricai") # Gets a logger named pediatricai, and all routers share this logger name so their messages appear together in the console with the same prefix
router = APIRouter(prefix="/patients", tags=["patients"]) # creates a router that  makes it so every endpoint in this file starts with /patients


@router.post("", response_model=PatientResponse, status_code=201)
def create_patient(patient: PatientCreate, db: Session = Depends(get_db)): # Creates a SQLAlchemy Patient object
    db_patient = Patient(
        name=patient.name, age=patient.age, sex=patient.sex,
        weight_kg=patient.weight_kg,
        known_conditions=patient.known_conditions,
        medications=patient.medications,
    )
    db.add(db_patient) # Tells the session to add a patient
    db.commit() # NOW writes it into the database, and if fails, it raises an exception
    db.refresh(db_patient) # Re-reads the object from the database
    logger.info(f"Created patient: {db_patient.id}")
    return db_patient


@router.get("/{patient_id}", response_model=PatientResponse) # FastAPI requests GET patient
def get_patient(patient_id: UUID, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first() # SQLAlchemy query. db.query(Patient) starts a SELECT on the patients table.
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.patch("/{patient_id}", response_model=PatientResponse) # This updates patient info
def update_patient(patient_id: UUID, updates: PatientUpdate, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    for field, value in updates.model_dump(exclude_unset=True).items(): # updates.model_dump(exclude_unset=True) converts the Pydantic model to a dictionary, but only includes fields the client actually sent
        setattr(patient, field, value)
    db.commit()
    db.refresh(patient)
    logger.info(f"Updated patient: {patient_id}")
    return patient


@router.get("", response_model=list[PatientResponse])
def list_patients(db: Session = Depends(get_db)): # This gets and lists all the patients
    return db.query(Patient).order_by(Patient.created_at.desc()).all()


@router.get("/{patient_id}/conversations", response_model=list[ConversationSummary])
def list_patient_conversations(patient_id: UUID, db: Session = Depends(get_db)): # Gets all conversations for this patient, newest first.
    conversations = db.query(Conversation).filter(
        Conversation.patient_id == patient_id
    ).order_by(Conversation.started_at.desc()).all()

    summaries = []
    for conv in conversations:
        msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
        last_msg = db.query(Message).filter( # Gets the most recent message and truncates to 80 characters for a preview. 
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).first()
        preview = (last_msg.content[:80] + "...") if last_msg else ""
        summaries.append(ConversationSummary(
            id=conv.id, started_at=conv.started_at,
            message_count=msg_count, last_message_preview=preview,
        ))
    return summaries # Builds and returns the summary objects.