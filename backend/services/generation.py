import logging
import time
import httpx
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()

SYSTEM_PROMPT = """You are PediatricAI, a friendly pediatrician. You speak directly to parents with warmth and confidence.

RULES:
- You ARE a doctor. Never say "I'm not a doctor" or "I can't provide medical advice." Give direct guidance.
- For emergencies (choking, not breathing, seizure, poisoning): Say "Call 911 right now." first, then give first-aid steps.
- For poisoning: "Call Poison Control at 1-800-222-1222 right now."
- Answer using the medical context provided below. If context is limited, use your general pediatric knowledge.
- Always give at least one thing the parent can do RIGHT NOW.
- Never give specific dosages (mg amounts). Say what the medicine does and tell them to ask their pediatrician for exact dosing.
- For off-topic questions (not health related): gently redirect to health topics.
- Structure responses: acknowledge concern → explain what it likely is → home care steps → when to call their pediatrician.
- Cite which source you used when possible.

EMERGENCY NUMBERS: 911 (emergencies), 1-800-222-1222 (Poison Control), 988 (Crisis Lifeline)""" # The system prompt is the instruction manual for the LLM, which defines a warm toned doctore

def build_prompt(user_message, retrieved_chunks, patient_info, conversation_history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] # This starts the message list with the system prompt

    patient_context = f"\n\nPATIENT: {patient_info.get('name', 'Unknown')}, Age {patient_info.get('age', '?')}, {patient_info.get('sex', '?')}"
    if patient_info.get('weight_kg'):
        patient_context += f", Weight {patient_info['weight_kg']}kg"
    if patient_info.get('known_conditions'):
        patient_context += f", Conditions: {', '.join(patient_info['known_conditions'])}"
    if patient_info.get('medications'):
        med_names = [m.get('name', str(m)) for m in patient_info['medications']]
        patient_context += f", Medications: {', '.join(med_names)}"

    context_text = "\n\nMEDICAL CONTEXT (use ONLY this for medical answers):\n" # Injects the retrieved chunks directly into the system prompt. Each chunk is labeled with its source and page number so the LLM cna cite it.
    if retrieved_chunks:
        for i, chunk in enumerate(retrieved_chunks, 1):
            context_text += f"\n[Source {i}: {chunk['doc_title']}, p.{chunk.get('page_num', '?')} | {chunk.get('section_type', 'general')}]\n{chunk['chunk_text']}\n"
    else:
        context_text += "\nNo relevant medical context found.\n"

    messages[0]["content"] += patient_context + context_text

    if conversation_history: # Adds the last 6 messages of conversation history. [-6:] takes the most recent 6 — enough for the LLM to understand follow-up questions
        for msg in conversation_history[-6:]:
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})
    return messages


async def generate_response(messages: list[dict]) -> dict: # Provider routing. Checks config to decide whether to use OpenAI (cloud, paid, better quality) or Ollama (local, free, lower quality)
    """Generate response using configured LLM provider."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return await _generate_openai(messages)
    return await _generate_ollama(messages)


async def _generate_ollama(messages: list[dict]) -> dict: # Creates an async HTTP client with a 120-second timeout.
    start_time = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{settings.ollama_host}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.3, "top_p": 0.9, "num_predict": 1024}, # 0.3 means that there is low randomness, as medical advice should be consistent, not creative. top_p = 0.9 only considers tokens whose cumulative probability is w/in the top 90%. num_predict=1024 is the maximum tokens to generate
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


async def _generate_openai(messages: list[dict]) -> dict: # OpenAI requires an API key in the Authorization header. Uses gpt-4o-mini
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


async def generate_response_stream(messages: list[dict]): # An async generator that yields one token at a time.
    """Streaming generator for SSE endpoint. Yields token strings."""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        async for token in _stream_openai(messages):
            yield token
    else:
        async for token in _stream_ollama(messages):
            yield token


async def _stream_ollama(messages: list[dict]): # client.stream() opens a streaming HTTP connection. Instead of waiting for the entire response, httpx receives data as Ollama generates it. 
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


async def _stream_openai(messages: list[dict]): # OpenAI's streaming format is SSE
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


def assess_urgency(answer: str, chunks: list[dict]) -> str: # Post-generation classification. Scans the LLM's response for urgency keywords
    answer_lower = answer.lower()
    if any(w in answer_lower for w in ["call 911", "emergency", "immediately", "right now"]):
        return "severe"
    if any(w in answer_lower for w in ["see a doctor", "see your pediatrician", "visit the er", "urgent care"]):
        return "moderate"
    if any(w in answer_lower for w in ["very common", "usually resolves", "nothing to worry", "completely normal"]):
        return "mild"
    return "none"