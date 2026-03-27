import logging
import time
import httpx
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()

SYSTEM_PROMPT = """You are a friendly, calm pediatrician named PediatricAI. You have a warm bedside manner and genuinely care about your patients.

CONVERSATION RULES:

(1) GREETINGS & CASUAL CHAT: For inputs like "hi", "thanks", "how are you" — respond warmly and in character as a kind doctor. Be human.

(2) OFF-TOPIC / NON-MEDICAL: For questions unrelated to health ("best jet fuel", "help with homework") — politely let them know you specialize in health questions and gently redirect. Stay warm, never scold.

(3) EMERGENCIES: For LIFE-THREATENING situations (choking, unconscious, not breathing, seizure, severe allergic reaction, severe bleeding, poisoning, blue lips, limp/unresponsive):
- Your FIRST sentence MUST be "Call 911 right now." — no preamble.
- Then provide step-by-step first-aid protocol from your medical context.
- For poisoning: "Call Poison Control at 1-800-222-1222 right now."
- For suicidal thoughts/self-harm: "Please call or text 988 right away."
- Include what NOT to do.

(4) MEDICAL QUESTIONS: For ANY health-related question:
- Answer ONLY using the provided medical context passages below.
- For EVERY condition, even ones needing professional care, ALWAYS provide at least one immediate comfort or bridge-care step the parent can do RIGHT NOW.
- Never leave a parent with only "see a doctor" and no actionable guidance.
- For minor/self-resolving conditions (scrapes, mild colds, bug bites, teething, cradle cap), provide complete home care and close the loop with reassurance. Do NOT default to "see a doctor" for trivial issues.
- For every medical claim, mention which source you used.

(5) MEDICATION SAFETY: NEVER provide specific dosages, milligram amounts, or weight-based calculations. Instead explain what the medication does, confirm it's generally appropriate for the age group, and recommend contacting their pediatrician or pharmacist for exact dosing.

(6) INSUFFICIENT INFORMATION: If the context does not contain enough information, say: "I don't have enough information to assess this — please see a doctor about [symptom]." Never guess.

HARDCODED NUMBERS (always available):
- 911 for emergencies
- 1-800-222-1222 for Poison Control
- 988 for Suicide & Crisis Lifeline
- Remind parents about their pediatrician's after-hours nurse line

RESPONSE FORMAT: Be conversational, warm, and clear. Use plain English. Structure longer responses: acknowledge → identify → explain → home care → what to expect → when to escalate → cite sources."""


def build_prompt(user_message, retrieved_chunks, patient_info, conversation_history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    patient_context = f"\n\nPATIENT: {patient_info.get('name', 'Unknown')}, Age {patient_info.get('age', '?')}, {patient_info.get('sex', '?')}"
    if patient_info.get('weight_kg'):
        patient_context += f", Weight {patient_info['weight_kg']}kg"
    if patient_info.get('known_conditions'):
        patient_context += f", Conditions: {', '.join(patient_info['known_conditions'])}"
    if patient_info.get('medications'):
        med_names = [m.get('name', str(m)) for m in patient_info['medications']]
        patient_context += f", Medications: {', '.join(med_names)}"

    context_text = "\n\nMEDICAL CONTEXT (use ONLY this for medical answers):\n"
    if retrieved_chunks:
        for i, chunk in enumerate(retrieved_chunks, 1):
            context_text += f"\n[Source {i}: {chunk['doc_title']}, p.{chunk.get('page_num', '?')} | {chunk.get('section_type', 'general')}]\n{chunk['chunk_text']}\n"
    else:
        context_text += "\nNo relevant medical context found.\n"

    messages[0]["content"] += patient_context + context_text

    if conversation_history:
        for msg in conversation_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})
    return messages


async def generate_response(messages: list[dict]) -> dict:
    """Generate response using configured LLM provider."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return await _generate_openai(messages)
    return await _generate_ollama(messages)


async def _generate_ollama(messages: list[dict]) -> dict:
    start_time = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.3, "top_p": 0.9, "num_predict": 1024},
            },
        )
        response.raise_for_status()
        data = response.json()

    elapsed_ms = int((time.time() - start_time) * 1000)
    return {
        "answer": data.get("message", {}).get("content", ""),
        "latency_ms": elapsed_ms,
        "tokens_used": data.get("eval_count", 0),
    }


async def _generate_openai(messages: list[dict]) -> dict:
    start_time = time.time()
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
            },
        )
        response.raise_for_status()
        data = response.json()

    elapsed_ms = int((time.time() - start_time) * 1000)
    return {
        "answer": data["choices"][0]["message"]["content"],
        "latency_ms": elapsed_ms,
        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
    }


async def generate_response_stream(messages: list[dict]):
    """Streaming generator for SSE endpoint. Yields token strings."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        async for token in _stream_openai(messages):
            yield token
    else:
        async for token in _stream_ollama(messages):
            yield token


async def _stream_ollama(messages: list[dict]):
    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": True,
                "options": {"temperature": 0.3, "top_p": 0.9, "num_predict": 1024},
            },
        ) as response:
            async for line in response.aiter_lines():
                if line.strip():
                    import json
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token


async def _stream_openai(messages: list[dict]):
    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream(
            "POST",
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 1024,
                "stream": True,
            },
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    import json
                    data = json.loads(line[6:])
                    token = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    if token:
                        yield token


def assess_urgency(answer: str, chunks: list[dict]) -> str:
    answer_lower = answer.lower()
    if any(w in answer_lower for w in ["call 911", "emergency", "immediately", "right now"]):
        return "severe"
    if any(w in answer_lower for w in ["see a doctor", "see your pediatrician", "visit the er", "urgent care"]):
        return "moderate"
    if any(w in answer_lower for w in ["very common", "usually resolves", "nothing to worry", "completely normal"]):
        return "mild"
    return "none"