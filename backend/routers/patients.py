import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.models.database import get_db, Patient, Conversation, Message
from backend.models.schemas import PatientCreate, PatientUpdate, PatientResponse, ConversationSummary

logger = logging.getLogger("pediatricai")
router = APIRouter(prefix="/patients", tags=["patients"])


@router.post("", response_model=PatientResponse, status_code=201)
def create_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    db_patient = Patient(
        name=patient.name, age=patient.age, sex=patient.sex,
        weight_kg=patient.weight_kg,
        known_conditions=patient.known_conditions,
        medications=patient.medications,
    )
    db.add(db_patient)
    db.commit()
    db.refresh(db_patient)
    logger.info(f"Created patient: {db_patient.id}")
    return db_patient


@router.get("/{patient_id}", response_model=PatientResponse)
def get_patient(patient_id: UUID, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.patch("/{patient_id}", response_model=PatientResponse)
def update_patient(patient_id: UUID, updates: PatientUpdate, db: Session = Depends(get_db)):
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    for field, value in updates.model_dump(exclude_unset=True).items():
        setattr(patient, field, value)
    db.commit()
    db.refresh(patient)
    logger.info(f"Updated patient: {patient_id}")
    return patient


@router.get("", response_model=list[PatientResponse])
def list_patients(db: Session = Depends(get_db)):
    return db.query(Patient).order_by(Patient.created_at.desc()).all()


@router.get("/{patient_id}/conversations", response_model=list[ConversationSummary])
def list_patient_conversations(patient_id: UUID, db: Session = Depends(get_db)):
    conversations = db.query(Conversation).filter(
        Conversation.patient_id == patient_id
    ).order_by(Conversation.started_at.desc()).all()

    summaries = []
    for conv in conversations:
        msg_count = db.query(Message).filter(Message.conversation_id == conv.id).count()
        last_msg = db.query(Message).filter(
            Message.conversation_id == conv.id
        ).order_by(Message.created_at.desc()).first()
        preview = (last_msg.content[:80] + "...") if last_msg else ""
        summaries.append(ConversationSummary(
            id=conv.id, started_at=conv.started_at,
            message_count=msg_count, last_message_preview=preview,
        ))
    return summaries