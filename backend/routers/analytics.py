import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from backend.models.database import get_db, Event, Message, SymptomExtraction
from backend.models.schemas import AnalyticsDashboard

logger = logging.getLogger("pediatricai")
router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/dashboard", response_model=AnalyticsDashboard)
def get_dashboard(db: Session = Depends(get_db)):
    total = db.query(Event).filter(Event.event_type == "query").count()

    avg_latency_result = db.execute(
        text("SELECT AVG((payload->>'latency_ms')::float) FROM events WHERE event_type = 'query'")
    ).scalar()
    avg_latency = round(float(avg_latency_result or 0), 1)

    refused_count = db.query(Message).filter(Message.refused == True).count()
    total_assistant = db.query(Message).filter(Message.role == "assistant").count()
    refusal_rate = round(refused_count / max(total_assistant, 1), 3)

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    queries_today = db.query(Event).filter(
        Event.event_type == "query", Event.created_at >= today_start,
    ).count()

    # Top symptoms from extractions
    top_symptoms_raw = db.execute(text("""
        SELECT symptom, COUNT(*) as cnt
        FROM symptom_extractions, jsonb_array_elements_text(symptoms) AS symptom
        GROUP BY symptom ORDER BY cnt DESC LIMIT 10
    """)).fetchall()
    top_symptoms = [{"symptom": row[0], "count": row[1]} for row in top_symptoms_raw]

    return AnalyticsDashboard(
        total_queries=total, avg_latency_ms=avg_latency,
        refusal_rate=refusal_rate, top_symptoms=top_symptoms,
        queries_today=queries_today,
    )