import logging
import time
import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.models.database import get_db, Patient, Conversation, Message, SymptomExtraction, Event
from backend.models.schemas import ChatRequest, ChatResponse, CitationItem
from backend.services.retrieval import search_chunks
from backend.services.generation import build_prompt, generate_response, generate_response_stream, assess_urgency
from backend.services.tts_service import synthesize_speech
from backend.services.evaluation import should_refuse, compute_confidence, is_low_confidence
from backend.utils.symptoms import extract_symptoms
from backend.services.clarification import detect_ambiguity
from backend.services.medication_safety import scan_text_for_medications, check_medication
from backend.services.dosing import compute_dose
from backend.services.dose_intent import (
    parse_dose_request, format_dose_answer, need_weight_message, format_safety_block,
)


# Severities we don't surface as a banner (a bare "couldn't verify" note is just noise).
# Allergy/duplicate/interaction/contraindication/cross-reactivity all rank above this and ARE surfaced.
_MED_NON_SURFACED_SEVERITIES = {"info"}


def medication_warnings_for(texts: list, patient_info: dict) -> list:
    """Deterministically screen every medication MENTIONED (user message) or RECOMMENDED
    (assistant answer) against this patient's allergies, current meds, age, and conditions.
    Runs in code (#1), so it can't silently miss a documented allergy the way prompt-only
    context can. Does NOT touch refusal/emergency/urgency — it only attaches warnings for the
    UI banner. Returns one dict per flagged medication; safe/unverifiable-only meds are omitted.
    """
    mentioned = []
    for t in texts:
        if not t:
            continue
        for name in scan_text_for_medications(t):
            if name not in mentioned:
                mentioned.append(name)

    out = []
    seen = set()
    for name in mentioned:
        result = check_medication(patient_info, name)
        meaningful = [w for w in result.warnings
                      if w["severity"] not in _MED_NON_SURFACED_SEVERITIES]
        if not meaningful:
            continue
        key = tuple(result.ingredients) or (name,)
        if key in seen:
            continue
        seen.add(key)
        payload = result.to_dict()
        payload["mentioned_as"] = name
        payload["warnings"] = meaningful
        out.append(payload)
    return out


def fix_broken_words(text: str) -> str:
    """Fix broken words that the LLM copied from PDF chunks."""
    fixes = {
        r'Ped\s*ial\s*y\s*te': 'Pedialyte', r'pediatric\s*ian': 'pediatrician',
        r'acet\s*amin\s*ophen': 'acetaminophen', r'Ty\s*len\s*ol': 'Tylenol',
        r'ibu\s*profen': 'ibuprofen', r'Mot\s*rin': 'Motrin', r'Ad\s*vil': 'Advil',
        r'hydr\s*ation': 'hydration', r'Hyd\s*ration': 'Hydration',
        r'de\s*hydration': 'dehydration', r're\s*hydration': 'rehydration',
        r'luk\s*ew\s*arm': 'lukewarm', r'Luk\s*ew\s*arm': 'Lukewarm',
        r'wors\s*ens': 'worsens', r'sc\s*arring': 'scarring',
        r'o\s*oz\s*ing': 'oozing', r'thick\s*ened': 'thickened',
        r'bund\s*ling': 'bundling', r'sh\s*ivering': 'shivering',
        r'd\s*rows\s*y': 'drowsy', r'ir\s*ritable': 'irritable',
        r'leth\s*argic': 'lethargic', r'ur\s*inating': 'urinating',
        r'com\s*ed\s*ogenic': 'comedogenic', r'oint\s*ment': 'ointment',
        r'Mo\s*ist\s*ur\s*ize': 'Moisturize', r'moist\s*urize': 'moisturize',
        r'Enc\s*ourage': 'Encourage', r'enc\s*ourage': 'encourage',
        r'Admin\s*ister': 'Administer', r'admin\s*ister': 'administer',
        r'Concentr\s*ation': 'Concentration', r'concentr\s*ation': 'concentration',
        r'R\s*ashes': 'Rashes', r'E\s*czema': 'Eczema',
        r'C\s*era\s*Ve': 'CeraVe', r'at\s*opic': 'atopic',
    }
    for pattern, replacement in fixes.items():
        text = re.sub(pattern, replacement, text)
    return text
logger = logging.getLogger("pediatricai")
router = APIRouter(prefix="/chat", tags=["chat"])

limiter = Limiter(key_func=get_remote_address)
@router.post("/query", response_model=ChatResponse)
@limiter.limit("15/hour")
async def chat_query(request: Request, body: ChatRequest, db: Session = Depends(get_db)):
    start_time = time.time()

    patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_info = {
        "name": patient.name, "age": patient.age, "sex": patient.sex,
        "weight_kg": patient.weight_kg,
        "known_conditions": patient.known_conditions or [],
        "medications": patient.medications or [],
    }

    if body.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(patient_id=patient.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_msg = Message(conversation_id=conversation.id, role="user", content=body.message)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # Used to check the ambiguity of the questions
    ambiguity = detect_ambiguity(body.message)
    if ambiguity["is_ambiguous"]:
        logger.info(f"Ambiguous query detected ({ambiguity['reason']}): {body.message[:60]}")
        answer = ambiguity["followup_question"]

        assistant_msg = Message(
            conversation_id=conversation.id, role="assistant", content=answer,
            citations=[], confidence_score=1.0, refused=False,
        )
        db.add(assistant_msg)

        elapsed_ms = int((time.time() - start_time) * 1000)
        event = Event(
            patient_id=patient.id, event_type="query",
            payload={
                "latency_ms": elapsed_ms, "tokens_used": 0,
                "retrieval_count": 0, "confidence": 1.0,
                "refused": False, "urgency": "none",
                "symptoms_extracted": [],
                "clarification_requested": True,
            },
        )
        db.add(event)
        db.commit()

        audio_base64 = None
        if body.voice_enabled:
            try:
                tts_result = await synthesize_speech(answer, body.doctor_gender)
                audio_base64 = tts_result["audio_base64"]
            except Exception as e:
                logger.warning(f"TTS failed: {e}")

        return ChatResponse(
            answer=answer, audio_base64=audio_base64, citations=[],
            confidence_score=1.0, refused=False, latency_ms=elapsed_ms,
            tokens_used=0, conversation_id=conversation.id, urgency="none", medication_warnings=medication_warnings_for([body.message], patient_info),
        )

    # --- NORMAL RAG PIPELINE ---
    symptom_data = extract_symptoms(body.message)
    if symptom_data["symptoms"]:
        extraction = SymptomExtraction(
            message_id=user_msg.id,
            symptoms=symptom_data["symptoms"],
            severity_estimate=symptom_data["severity_estimate"],
        )
        db.add(extraction)
        db.commit()

    age_range = "pediatric" if patient.age < 18 else None
    chunks = search_chunks(db, body.message, age_range=age_range)

    refused = should_refuse(chunks)
    confidence = compute_confidence(chunks)

    if refused:
        history_msgs = db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at).all()
        history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

        messages = build_prompt(body.message, [], patient_info, history)
        result = await generate_response(messages)

        answer = result["answer"]
        answer = fix_broken_words(answer)
        tokens_used = result["tokens_used"]
        urgency = assess_urgency(answer, chunks)
        citations = []
        refused = False
        confidence = 0.3
    else:
        history_msgs = db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at).all()
        history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

        messages = build_prompt(body.message, chunks, patient_info, history)
        result = await generate_response(messages)

        answer = result["answer"]
        answer = fix_broken_words(answer)
        tokens_used = result["tokens_used"]
        urgency = assess_urgency(answer, chunks)

        citations = [
            CitationItem(
                doc_title=c["doc_title"], source=c["doc_source"],
                page_num=c.get("page_num"), section_type=c.get("section_type"),
                excerpt=c["chunk_text"][:200] + ("..." if len(c["chunk_text"]) > 200 else ""),
                similarity_score=round(c["similarity"], 3),
            )
            for c in chunks[:5]
        ]

    audio_base64 = None
    if body.voice_enabled:
        try:
            tts_result = await synthesize_speech(answer, body.doctor_gender)
            audio_base64 = tts_result["audio_base64"]
        except Exception as e:
            logger.warning(f"TTS failed (graceful degradation): {e}")

    assistant_msg = Message(
        conversation_id=conversation.id, role="assistant", content=answer,
        citations=[c.model_dump() for c in citations],
        confidence_score=confidence, refused=refused,
    )
    db.add(assistant_msg)

    elapsed_ms = int((time.time() - start_time) * 1000)
    event = Event(
        patient_id=patient.id, event_type="query",
        payload={
            "latency_ms": elapsed_ms, "tokens_used": tokens_used,
            "retrieval_count": len(chunks), "confidence": confidence,
            "refused": refused, "urgency": urgency,
            "symptoms_extracted": symptom_data["symptoms"],
        },
    )
    db.add(event)
    db.commit()

    return ChatResponse(
        answer=answer, audio_base64=audio_base64, citations=citations,
        confidence_score=confidence, refused=refused, latency_ms=elapsed_ms,
        tokens_used=tokens_used, conversation_id=conversation.id, urgency=urgency,medication_warnings=medication_warnings_for([body.message, answer], patient_info),
    )
@router.post("/stream")
@limiter.limit("15/hour")
async def chat_stream(request: Request, body: ChatRequest, db: Session = Depends(get_db)):
    """SSE streaming endpoint - sends tokens as they generate."""
    patient = db.query(Patient).filter(Patient.id == body.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_info = {
        "name": patient.name, "age": patient.age, "sex": patient.sex,
        "weight_kg": patient.weight_kg,
        "known_conditions": patient.known_conditions or [],
        "medications": patient.medications or [],
    }

    if body.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(patient_id=patient.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_msg = Message(conversation_id=conversation.id, role="user", content=body.message)
    db.add(user_msg)
    db.commit()

    conv_id = conversation.id
    patient_id_val = patient.id

    # If the parent is asking HOW MUCH of a known OTC antipyretic to give, answer from
    # compute_dose (code) instead of the model, so the milligrams are never guessed.
    # Precedence: (1) allergy/contraindication vetoes the dose, (2) no weight -> ask,
    # (3) otherwise compute and format the real numbers.
    dose_req = parse_dose_request(body.message, patient_info)
    if dose_req:
        dose_med_warnings = medication_warnings_for([body.message], patient_info)
        blocking = [p for p in dose_med_warnings if p.get("blocked")]
        if blocking:
            dose_answer = format_safety_block(blocking)
        elif dose_req["weight_kg"] is None:
            dose_answer = need_weight_message(dose_req["drug"])
        else:
            dose_result = compute_dose(
                dose_req["drug"],
                weight_kg=dose_req["weight_kg"],
                age_months=dose_req["age_months"],
                age_years=dose_req["age_years"],
                known_conditions=dose_req["known_conditions"],
            )
            dose_answer = format_dose_answer(dose_result, patient.name)
            cautions = [w["message"] for p in dose_med_warnings if not p.get("blocked")
                        for w in p.get("warnings", [])]
            if cautions and dose_result.ok:
                dose_answer = " ".join(cautions) + " " + dose_answer

        db.add(Message(
            conversation_id=conv_id, role="assistant", content=dose_answer,
            citations=[], confidence_score=1.0, refused=False,
        ))
        db.commit()

        async def dose_generator():
            if dose_med_warnings:
                yield {"event": "medication_warning", "data": json.dumps(dose_med_warnings)}
            words = dose_answer.split(" ")
            for i, w in enumerate(words):
                yield {"event": "token", "data": (w if i == 0 else " " + w)}
            yield {"event": "done", "data": json.dumps({
                "conversation_id": str(conv_id),
                "refused": False, "confidence_score": 1.0, "urgency": "none",
                "citations": [], "cleaned_answer": dose_answer,
                "medication_warnings": dose_med_warnings,
            })}

        return EventSourceResponse(dose_generator())
    # ------------------------------------------------------------------------------

    # --- AMBIGUITY CHECK (before retrieval) ---
    ambiguity = detect_ambiguity(body.message)

    if ambiguity["is_ambiguous"]:
        logger.info(f"Ambiguous query detected ({ambiguity['reason']}): {body.message[:60]}")
        clarification = ambiguity["followup_question"]

        assistant_msg = Message(
            conversation_id=conv_id, role="assistant", content=clarification,
            citations=[], confidence_score=1.0, refused=False,
        )
        db.add(assistant_msg)
        db.commit()

        async def clarification_generator():
            words = clarification.split(" ")
            for i, word in enumerate(words):
                token = word if i == 0 else " " + word
                yield {"event": "token", "data": token}

            yield {"event": "done", "data": json.dumps({
                "conversation_id": str(conv_id),
                "refused": False, "confidence_score": 1.0,
                "urgency": "none", "citations": [],
            })}

        return EventSourceResponse(clarification_generator())

    # NORMAL RAG PIPELINE
    age_range = "pediatric" if patient.age < 18 else None
    chunks = search_chunks(db, body.message, age_range=age_range)

    refused = should_refuse(chunks)

    history_msgs = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).all()
    history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

    # Deterministic safety scan on the user's message (#1), computed before any tokens
    # so the UI can raise the banner immediately; independent of refusal.
    user_med_warnings = medication_warnings_for([body.message], patient_info)

    async def event_generator():
        if user_med_warnings:
            yield {"event": "medication_warning", "data": json.dumps(user_med_warnings)}
        if refused:
            messages_for_llm = build_prompt(body.message, [], patient_info, history)
            full_answer = ""
            async for token in generate_response_stream(messages_for_llm):
                full_answer += token
                yield {"event": "token", "data": token}

            full_answer = fix_broken_words(full_answer)
            confidence = 0.3
            urgency = assess_urgency(full_answer, [])

            from backend.services.generation import fix_output_text
            full_answer = fix_output_text(full_answer)
            assistant_msg = Message(
                conversation_id=conv_id, role="assistant", content=full_answer,
                citations=[], confidence_score=confidence, refused=False,
            )
            db.add(assistant_msg)
            db.commit()

            yield {"event": "done", "data": json.dumps({
                "conversation_id": str(conv_id),
                "refused": False, "confidence_score": confidence,
                "urgency": urgency, "citations": [],
                "cleaned_answer": full_answer, "medication_warnings": medication_warnings_for([body.message, full_answer], patient_info),
            })}
            return

        messages_for_llm = build_prompt(body.message, chunks, patient_info, history)

        full_answer = ""
        async for token in generate_response_stream(messages_for_llm):
            full_answer += token
            yield {"event": "token", "data": token}

        full_answer = fix_broken_words(full_answer)
        urgency = assess_urgency(full_answer, chunks)
        confidence = compute_confidence(chunks)
        citation_dicts = [
            {"doc_title": c["doc_title"], "source": c["doc_source"],
             "page_num": c.get("page_num"), "section_type": c.get("section_type"),
             "excerpt": c["chunk_text"][:200], "similarity_score": round(c["similarity"], 3)}
            for c in chunks[:5]
        ]
        from backend.services.generation import fix_output_text
        full_answer = fix_output_text(full_answer)
        assistant_msg = Message(
            conversation_id=conv_id, role="assistant", content=full_answer,
            citations=citation_dicts, confidence_score=confidence, refused=False,
        )
        db.add(assistant_msg)
        db.commit()

        yield {"event": "done", "data": json.dumps({
            "conversation_id": str(conv_id),
            "refused": False, "confidence_score": confidence,
            "urgency": urgency, "citations": citation_dicts,
            "cleaned_answer": full_answer,
        })}

    return EventSourceResponse(event_generator())


@router.get("/history/{conversation_id}")
def get_conversation_history(conversation_id: UUID, db: Session = Depends(get_db)):
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(Message.created_at).all()

    return {
        "conversation_id": str(conversation.id),
        "patient_id": str(conversation.patient_id),
        "started_at": conversation.started_at.isoformat(),
        "messages": [
            {
                "id": str(m.id), "role": m.role, "content": m.content,
                "citations": m.citations, "confidence_score": m.confidence_score,
                "refused": m.refused, "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }