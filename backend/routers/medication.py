"""
Medication endpoints (TIER 1).

Surfaces the three deterministic medication services to the API:

  * #2 dose calculator  -> POST /medication/dose-calc
  * #1 safety layer      -> POST /medication/safety-check  (+ /{patient_id} convenience)
  * #3 dose log + guard  -> /medication/patients/{patient_id}/doses ...

Every dosing/safety number returned here is computed in the deterministic services
(backend/services/dosing.py, medication_safety.py, dose_log.py). The LLM is never
involved in producing a dose, an interval, or a safety verdict — it can only route a
user to these endpoints.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.models.database import get_db, Patient, Dose
from backend.models.schemas import (
    DoseCalcRequest, DoseCalcResponse,
    MedSafetyRequest, MedSafetyResponse,
    DoseCreate, DoseResponse, NextDoseResponse,
    DoseGuardRequest, DoseGuardResponse,
)
from backend.services.dosing import compute_dose
from backend.services.medication_safety import check_medication
from backend.services.dose_log import next_safe_dose, check_proposed_dose

logger = logging.getLogger("pediatricai")
router = APIRouter(prefix="/medication", tags=["medication"])


# ---------------------------------------------------------------------------
# #2 — Weight-based OTC dose calculator (acetaminophen + ibuprofen only)
# ---------------------------------------------------------------------------
@router.post("/dose-calc", response_model=DoseCalcResponse)
def dose_calc(req: DoseCalcRequest):
    """Deterministic single-dose + interval for acetaminophen/ibuprofen.

    Returns 200 with ok=False (not an HTTP error) when the calculator deliberately
    refuses — unsupported drug, missing weight, age floor, or a deferring condition —
    so the frontend can render the reason instead of a dose. The numbers come straight
    from the published dosing table; the LLM is not consulted.
    """
    result = compute_dose(
        drug=req.drug,
        weight_kg=req.weight_kg,
        weight_lb=req.weight_lb,
        age_months=req.age_months,
        age_years=req.age_years,
        known_conditions=req.known_conditions,
    )
    return result.to_dict()

# #1 — Deterministic medication safety layer (allergy / duplicate / interaction)
@router.post("/safety-check", response_model=MedSafetyResponse)
def safety_check(req: MedSafetyRequest):
    """Screen `drug` against patient context supplied in the request body.

    blocked=True means a hard conflict (documented allergy or pediatric
    contraindication); the caller must not present the drug as safe.
    """
    patient = {
        "age": req.age,
        "age_years": req.age_years,
        "known_conditions": req.known_conditions,
        "medications": req.medications,
    }
    return check_medication(patient, req.drug).to_dict()

@router.get("/safety-check/{patient_id}", response_model=MedSafetyResponse)
def safety_check_for_patient(patient_id: UUID, drug: str = Query(..., min_length=1),
                             db: Session = Depends(get_db)):
    """Same check, but pulls the stored patient record so the screen runs against the
    real allergy/medication list on file rather than client-supplied context."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    patient_ctx = {
        "age": patient.age,
        "known_conditions": patient.known_conditions or [],
        "medications": patient.medications or [],
    }
    return check_medication(patient_ctx, drug).to_dict()

# #3 — Medication log + schedule + double-dose guard
@router.post("/patients/{patient_id}/doses", response_model=DoseResponse, status_code=201)
def log_dose(patient_id: UUID, dose: DoseCreate, db: Session = Depends(get_db)):
    """Record a dose that was given. given_at defaults to now if the caller omits it."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    db_dose = Dose(
        patient_id=patient_id,
        drug=dose.drug,
        amount_mg=dose.amount_mg,
        note=dose.note,
        **({"given_at": dose.given_at} if dose.given_at is not None else {}),
    )
    db.add(db_dose)
    db.commit()
    db.refresh(db_dose)
    logger.info(f"Logged dose {db_dose.id} ({dose.drug}) for patient {patient_id}")
    return db_dose

@router.get("/patients/{patient_id}/doses", response_model=list[DoseResponse])
def list_doses(patient_id: UUID, db: Session = Depends(get_db)):
    """All logged doses for a patient, most recent first."""
    return (
        db.query(Dose)
        .filter(Dose.patient_id == patient_id)
        .order_by(Dose.given_at.desc())
        .all()
    )

@router.get("/patients/{patient_id}/doses/next", response_model=NextDoseResponse)
def next_dose(patient_id: UUID, drug: str = Query(..., min_length=1),
              db: Session = Depends(get_db)):
    """When the next dose of `drug` is safe, based on this patient's logged doses."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    prior = _dose_dicts(db, patient_id)
    return next_safe_dose(drug, prior).to_dict()

@router.post("/patients/{patient_id}/doses/check", response_model=DoseGuardResponse)
def guard_proposed_dose(patient_id: UUID, req: DoseGuardRequest,
                        db: Session = Depends(get_db)):
    """Deterministically decide whether giving `drug` right now is safe given the log:
    blocks a too-early re-dose or a 24-hour-cap breach (by count or by milligrams)."""
    patient = db.query(Patient).filter(Patient.id == patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    prior = _dose_dicts(db, patient_id)
    weight = req.weight_kg if req.weight_kg is not None else patient.weight_kg
    result = check_proposed_dose(
        drug=req.drug,
        prior_doses=prior,
        proposed_amount_mg=req.proposed_amount_mg,
        weight_kg=weight,
    )
    return result.to_dict()

def _dose_dicts(db: Session, patient_id: UUID) -> list:
    """Load a patient's doses as plain dicts for the pure dose-log functions."""
    rows = db.query(Dose).filter(Dose.patient_id == patient_id).all()
    return [{"drug": r.drug, "given_at": r.given_at, "amount_mg": r.amount_mg} for r in rows]
