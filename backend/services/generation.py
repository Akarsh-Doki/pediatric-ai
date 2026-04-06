import logging
import time
import re
import httpx
from backend.config import get_settings
from spellchecker import SpellChecker

logger = logging.getLogger("pediatricai")

_spell = SpellChecker()
# Add medical/brand terms the default dictionary might miss
_spell.word_frequency.load_words([
    'pedialyte', 'tylenol', 'motrin', 'advil', 'zyrtec', 'benadryl',
    'amoxicillin', 'acetaminophen', 'ibuprofen', 'cerave', 'aquaphor',
    'pediatrician', 'bronchiolitis', 'comedogenic', 'dermatitis',
    'nebulizer', 'humidifier', 'thermometer', 'dehydration',
    'rehydration', 'otitis', 'streptococcal', 'meningitis',
])


def fix_output_text(text: str) -> str:
    """
    Rejoin broken words in LLM output using dictionary lookup.
    
    When the LLM copies broken words from PDF chunks (e.g. 'pediatric ian'),
    this function detects non-dictionary fragments and joins them with
    neighbors until they form valid English words.
    """
    words = text.split(' ')
    result = []
    i = 0
    while i < len(words):
        word = words[i]
        # Strip punctuation for dictionary check, keep original for output
        clean = re.sub(r'[^a-zA-Z]', '', word)

        # If it's a real word, number, empty, single char, or markdown, keep it
        if not clean or clean.lower() in _spell or len(clean) <= 1 or word.startswith('**') or word.startswith('-'):
            result.append(word)
            i += 1
            continue

        # Not a real word — try joining with next 1-4 words
        joined = word
        best = None
        for j in range(i + 1, min(i + 5, len(words))):
            joined += words[j]
            clean_joined = re.sub(r'[^a-zA-Z]', '', joined)
            if clean_joined.lower() in _spell:
                best = (joined, j + 1)
                break

        if best:
            result.append(best[0])
            i = best[1]
        else:
            result.append(word)
            i += 1

    return ' '.join(result)


SYSTEM_PROMPT = """You are PediatricAI, a friendly pediatrician. You speak directly to parents with warmth and confidence.

RULES:
- You ARE a doctor. Never say "I'm not a doctor" or "I can't provide medical advice." Give direct guidance.
- For emergencies (choking, not breathing, seizure, poisoning): Say "Call 911 right now." first, then give first-aid steps.
- For poisoning: "Call Poison Control at 1-800-222-1222 right now."
- Answer using the medical context provided below. If context is limited, use your general pediatric knowledge.
- Always give at least one thing the parent can do RIGHT NOW.
- Never give specific dosages (mg amounts). Say what the medicine does and tell them to ask their pediatrician for exact dosing.
- For off-topic questions (not health related): gently redirect to health topics.
- Structure responses: acknowledge concern -> explain what it likely is -> home care steps -> when to call their pediatrician.
- Cite which source you used when possible.
- IMPORTANT: The medical context may contain broken words from PDF extraction. Always write every word with correct spelling in your response.

EMERGENCY NUMBERS: 911 (emergencies), 1-800-222-1222 (Poison Control), 988 (Crisis Lifeline)"""


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
    settings = get_settings()
    if settings.llm_provider == "openai" and settings.openai_api_key:
        result = await _generate_openai(messages)
    else:
        result = await _generate_ollama(messages)
    result["answer"] = fix_output_text(result["answer"])
    return result


async def _generate_ollama(messages: list[dict]) -> dict:
    settings = get_settings()
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
    settings = get_settings()
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
                "max_tokens": 800,
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
    """
    Streaming generator that collects full response, fixes broken words,
    then re-streams word by word for frontend animation.
    """
    settings = get_settings()
    logger.info(f"STREAM PROVIDER: {settings.llm_provider}, KEY SET: {bool(settings.openai_api_key)}")

    # Collect all tokens first
    full_text = ""
    if settings.llm_provider == "openai" and settings.openai_api_key:
        async for token in _stream_openai(messages):
            full_text += token
    else:
        async for token in _stream_ollama(messages):
            full_text += token

    # Fix broken words on complete text
    fixed = fix_output_text(full_text)

    # Re-stream word by word for the frontend animation
    words = fixed.split(' ')
    for i, word in enumerate(words):
        token = word if i == 0 else ' ' + word
        yield token


async def _stream_ollama(messages: list[dict]):
    settings = get_settings()
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
    settings = get_settings()
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
                "max_tokens": 800,
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