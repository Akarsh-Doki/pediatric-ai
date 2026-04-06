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

    # --- AMBIGUITY CHECK (runs before retrieval to save compute) ---
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
            tokens_used=0, conversation_id=conversation.id, urgency="none",
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
        tokens_used=tokens_used, conversation_id=conversation.id, urgency=urgency,
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

    # --- NORMAL RAG PIPELINE ---
    age_range = "pediatric" if patient.age < 18 else None
    chunks = search_chunks(db, body.message, age_range=age_range)

    refused = should_refuse(chunks)

    history_msgs = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).all()
    history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

    async def event_generator():
        if refused:
            messages_for_llm = build_prompt(body.message, [], patient_info, history)
            full_answer = ""
            async for token in generate_response_stream(messages_for_llm):
                full_answer += token
                yield {"event": "token", "data": token}

            full_answer = fix_broken_words(full_answer)
            confidence = 0.3
            urgency = assess_urgency(full_answer, [])

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