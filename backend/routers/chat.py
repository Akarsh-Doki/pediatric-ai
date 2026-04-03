import logging
import time # time is used to measure the latency of each query
import json # serializing SSE "done" event metadata
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse # This is to provide Server-Sent Events, which is a protocol where the server pushes data to the client over a single HTTP connection. SSE is one way: server -> client. This is best for LLM token, where the server sends each token as it generates, and the frontend displays it immediately

from backend.models.database import get_db, Patient, Conversation, Message, SymptomExtraction, Event
from backend.models.schemas import ChatRequest, ChatResponse, CitationItem
from backend.services.retrieval import search_chunks
from backend.services.generation import build_prompt, generate_response, generate_response_stream, assess_urgency
from backend.services.tts_service import synthesize_speech
from backend.services.evaluation import should_refuse, compute_confidence, is_low_confidence
from backend.utils.symptoms import extract_symptoms
from backend.services.clarification import detect_ambiguity
# Every service in the RAG pipeline imported from the backend

logger = logging.getLogger("pediatricai")
router = APIRouter(prefix="/chat", tags=["chat"])

REFUSAL_MESSAGE = "I don't have enough information in my medical references to assess this safely. I'd recommend reaching out to your pediatrician \u2014 they'll be able to help. If it's after hours, most pediatrician offices have a nurse line you can call." # This is the response for hard refusals, only used if similarity is less than 0.45, but its very rare


@router.post("/query", response_model=ChatResponse)
async def chat_query(request: ChatRequest, db: Session = Depends(get_db)):
    start_time = time.time() # Captures the moment that the request begins

    patient = db.query(Patient).filter(Patient.id == request.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found") # This checks if the patient exists, if not, sends a 404 error

    patient_info = {
        "name": patient.name, "age": patient.age, "sex": patient.sex,
        "weight_kg": patient.weight_kg,
        "known_conditions": patient.known_conditions or [],
        "medications": patient.medications or [],
    } # converts the SQLAlchemy object into a plain dict, which gets injected into the LLM prompt

    # Get or create conversation using the first message
    if request.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == request.conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(patient_id=patient.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    # Save user message to the database immediately
    user_msg = Message(conversation_id=conversation.id, role="user", content=request.message)
    db.add(user_msg)
    db.commit()
    db.refresh(user_msg)

    # --- AMBIGUITY CHECK (runs before retrieval to save compute) ---
    ambiguity = detect_ambiguity(request.message)
    if ambiguity["is_ambiguous"]:
        logger.info(f"Ambiguous query detected ({ambiguity['reason']}): {request.message[:60]}")
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
        if request.voice_enabled:
            try:
                tts_result = await synthesize_speech(answer, request.doctor_gender)
                audio_base64 = tts_result["audio_base64"]
            except Exception as e:
                logger.warning(f"TTS failed: {e}")

        return ChatResponse(
            answer=answer, audio_base64=audio_base64, citations=[],
            confidence_score=1.0, refused=False, latency_ms=elapsed_ms,
            tokens_used=0, conversation_id=conversation.id, urgency="none",
        )

    # Extract symptoms from user message using keywords extraction, and adds to db
    symptom_data = extract_symptoms(request.message)
    if symptom_data["symptoms"]:
        extraction = SymptomExtraction(
            message_id=user_msg.id,
            symptoms=symptom_data["symptoms"],
            severity_estimate=symptom_data["severity_estimate"],
        )
        db.add(extraction)
        db.commit()

    # Retrieve relevant chunks (R in RAG) by embedding the question
    age_range = "pediatric" if patient.age < 18 else None
    chunks = search_chunks(db, request.message, age_range=age_range)

    refused = should_refuse(chunks) # This returns True if the best chunk similarity is below 0.45
    confidence = compute_confidence(chunks) # calculates the weighted score (0.6 × best + 0.4 × average)

    if refused:
        # Still try to help with general knowledge instead of hard refusing by using the LLM's general knowledge through a prompt
        history_msgs = db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at).all()
        history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

        messages = build_prompt(request.message, [], patient_info, history)
        result = await generate_response(messages)

        answer = result["answer"]
        tokens_used = result["tokens_used"]
        urgency = assess_urgency(answer, chunks)
        citations = []
        refused = False
        confidence = 0.3
    else: # This is the normal RAG path, which fetches conversation history and excludes the current message
        history_msgs = db.query(Message).filter(
            Message.conversation_id == conversation.id
        ).order_by(Message.created_at).all()
        history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

        messages = build_prompt(request.message, chunks, patient_info, history) # Builds the full prompt (system prompt + patient info + medical context chunks + conversation history + user question) and sends it to the LLM.
        result = await generate_response(messages)

        answer = result["answer"]
        tokens_used = result["tokens_used"]
        urgency = assess_urgency(answer, chunks)

        citations = [
            CitationItem( # citing sources
                doc_title=c["doc_title"], source=c["doc_source"],
                page_num=c.get("page_num"), section_type=c.get("section_type"),
                excerpt=c["chunk_text"][:200] + ("..." if len(c["chunk_text"]) > 200 else ""),
                similarity_score=round(c["similarity"], 3),
            )
            for c in chunks[:5]
        ]

    # Generate TTS - If voice is enabled, converts the answer text to speech. 
    audio_base64 = None
    if request.voice_enabled:
        try:
            tts_result = await synthesize_speech(answer, request.doctor_gender)
            audio_base64 = tts_result["audio_base64"]
        except Exception as e:
            logger.warning(f"TTS failed (graceful degradation): {e}")

    # Save assistant message to the database
    assistant_msg = Message(
        conversation_id=conversation.id, role="assistant", content=answer,
        citations=[c.model_dump() for c in citations],
        confidence_score=confidence, refused=refused,
    )
    db.add(assistant_msg)

    elapsed_ms = int((time.time() - start_time) * 1000) # Calculates total latency (time.time() - start_time in milliseconds) and saves everything to the events table. 
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

    return ChatResponse( # Returns the complete response
        answer=answer, audio_base64=audio_base64, citations=citations,
        confidence_score=confidence, refused=refused, latency_ms=elapsed_ms,
        tokens_used=tokens_used, conversation_id=conversation.id, urgency=urgency,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest, db: Session = Depends(get_db)):
    """SSE streaming endpoint - sends tokens as they generate."""
    patient = db.query(Patient).filter(Patient.id == request.patient_id).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    patient_info = {
        "name": patient.name, "age": patient.age, "sex": patient.sex,
        "weight_kg": patient.weight_kg,
        "known_conditions": patient.known_conditions or [],
        "medications": patient.medications or [],
    }

    if request.conversation_id:
        conversation = db.query(Conversation).filter(Conversation.id == request.conversation_id).first()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(patient_id=patient.id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    user_msg = Message(conversation_id=conversation.id, role="user", content=request.message) # . After db.commit(), SQLAlchemy detaches the conversation and patient objects from the session. If the async generator later tries conversation.id, SQLAlchemy attempts a database query on a closed session and crashes with DetachedInstanceError
    db.add(user_msg)
    db.commit()

    # Capture IDs as plain values BEFORE the async generator
    # (SQLAlchemy objects get detached from the session after commit)
    conv_id = conversation.id
    patient_id_val = patient.id

    # --- AMBIGUITY CHECK (before retrieval) ---
    ambiguity = detect_ambiguity(request.message)

    if ambiguity["is_ambiguous"]:
        logger.info(f"Ambiguous query detected ({ambiguity['reason']}): {request.message[:60]}")
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
    chunks = search_chunks(db, request.message, age_range=age_range)

    refused = should_refuse(chunks)

    # Pre-fetch history BEFORE the generator (while db session is active)
    history_msgs = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).all()
    history = [{"role": m.role, "content": m.content} for m in history_msgs[:-1]]

    async def event_generator():
        if refused:
            # Fallback: Even when retrieval found nothing, the LLM streams using general knowledge. generate_response_stream is an async generator that yields one token at a time 
            messages_for_llm = build_prompt(request.message, [], patient_info, history)
            full_answer = ""
            async for token in generate_response_stream(messages_for_llm):
                full_answer += token
                yield {"event": "token", "data": token}
            confidence = 0.3
            urgency = assess_urgency(full_answer, []) # After streaming completes, assess the full answer for urgency keywords.
            citation_dicts = []

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
        messages_for_llm = build_prompt(request.message, chunks, patient_info, history)

        full_answer = ""
        async for token in generate_response_stream(messages_for_llm):
            full_answer += token
            yield {"event": "token", "data": token}

        urgency = assess_urgency(full_answer, chunks)
        confidence = compute_confidence(chunks)
        citation_dicts = [
            {"doc_title": c["doc_title"], "source": c["doc_source"],
             "page_num": c.get("page_num"), "section_type": c.get("section_type"),
             "excerpt": c["chunk_text"][:200], "similarity_score": round(c["similarity"], 3)}
            for c in chunks[:5]
        ]

        # Save assistant message
        assistant_msg = Message(
            conversation_id=conv_id, role="assistant", content=full_answer,
            citations=citation_dicts, confidence_score=confidence, refused=False,
        )
        db.add(assistant_msg)
        db.commit()

        yield {"event": "done", "data": json.dumps({ # The final SSE event, which sends metadata (conversation ID, confidence, urgency, citations) as a JSON string
            "conversation_id": str(conv_id),
            "refused": False, "confidence_score": confidence,
            "urgency": urgency, "citations": citation_dicts,
        })}

    return EventSourceResponse(event_generator())

@router.get("/history/{conversation_id}")
def get_conversation_history(conversation_id: UUID, db: Session = Depends(get_db)): # Loads a past conversation. Used when a user clicks a conversation in the sidebar.
    conversation = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(Message).filter( # Gets all messages in chronological order.
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