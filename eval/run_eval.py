"""
RAG on vs. RAG off evaluation with an LLM claim-checking judge.

For every question in eval/questions.csv (60 answerable from the corpus, 20 out of scope):

  1. RAG OFF — the app's own system prompt + the question, with NO retrieved context.
  2. RAG ON  — the same path as POST /chat/query: ambiguity check -> pgvector retrieval
               -> refusal gate -> build_prompt -> LLM -> the same text clean-up.

Both arms use the SAME model the app is configured for (settings.llm_provider), at
temperature 0. The only variable that changes between arms is retrieval.

Each answer is then graded by a separate judge model that lists every medical claim and
checks it against source excerpts pulled from the corpus. The final label is computed in
code from the judge's structured output:

    Unsupported  any medical claim not found in, or contradicting, the source excerpts
    Declined     says it can't answer, and makes no unsupported claims
    Correct      matches the reference answer, and every claim is supported
    Incomplete   every claim is supported but it doesn't give the reference answer
                 (needed because the three labels above don't cover every answer)

Nothing in backend/ is modified; the app's functions are imported and called as-is. The
one intentional difference from production is temperature (0 here, 0.3 in the app), so
that runs are repeatable.

Usage (repo root, DB up, same env as the API):

    python -m eval.run_eval --limit 3          # smoke test on 3 questions
    python -m eval.run_eval                    # full run -> results.csv, hand_check.csv
    python -m eval.run_eval --resume           # continue after a crash, reusing finished rows
    python -m eval.run_eval --summary-only     # re-print the table from results.csv
    python -m eval.run_eval --compare-hand-check   # judge vs. your hand grades

    # Cheap iteration: only the RAG-on arm, a small judge, parallel, separate output files
    python -m eval.run_eval --arms on --judge-model gpt-4o-mini --concurrency 12 --tag run1
    # Re-grade a finished run's exact answers with a stronger judge and report agreement
    python -m eval.run_eval --rejudge eval/runs/run1_results.csv --judge-model gpt-4o
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import random
import re
import sys
from collections import Counter
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVAL_DIR / "runs"
QUESTIONS_CSV = EVAL_DIR / "questions.csv"
RESULTS_CSV = EVAL_DIR / "results.csv"
HAND_CHECK_CSV = EVAL_DIR / "hand_check.csv"
CACHE_JSONL = EVAL_DIR / "results_cache.jsonl"

# generation.py hardcodes this model for the OpenAI provider; mirrored here.
APP_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_JUDGE_MODEL = "gpt-4o"

# A neutral patient, identical for both arms. The seeded demo patient (a 4-year-old with
# eczema) would contradict questions about newborns or teenagers.
EVAL_PATIENT = {"name": "Parent", "age": "not specified", "sex": "not specified"}

TOP_K_FOR_RECALL = 5
EVIDENCE_PER_SENTENCE = 2   # nearest corpus chunks fetched per answer sentence for the judge
MAX_EVIDENCE_CHUNKS = 16    # judge input is the main cost; ~390 tokens per chunk
HAND_CHECK_N = 25
VERDICTS = ["Correct", "Unsupported", "Declined", "Incomplete"]
_RETRYABLE = {429, 500, 502, 503, 504}

# USD per 1M tokens: (input, cached input, output). Used only to print a cost estimate;
# update if OpenAI's prices change.
PRICES = {"gpt-4o-mini": (0.15, 0.075, 0.60), "gpt-4o": (2.50, 1.25, 10.00),
          "gpt-4.1-mini": (0.40, 0.10, 1.60)}
USAGE: dict[str, Counter] = {}


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------
def load_questions(path: Path = QUESTIONS_CSV) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["in_scope"] = r["in_scope"].strip().lower() == "yes"
        r["gold_ids"] = [c for c in r["supporting_chunk_ids"].split(";") if c]
    return rows


def load_corpus(db) -> dict:
    """All chunks keyed two ways: DB UUID and the stable '<pdf filename>#<chunk_index>' id
    used in questions.csv. UUIDs change on every re-ingest; filename + index does not."""
    from sqlalchemy import text

    rows = db.execute(text("""
        SELECT c.id, c.chunk_index, c.chunk_text, d.file_path
        FROM chunks c JOIN guideline_docs d ON c.doc_id = d.id
    """)).fetchall()
    by_uuid, by_stable = {}, {}
    for r in rows:
        stable = f"{Path(r.file_path).name}#{r.chunk_index}"
        by_uuid[str(r.id)] = stable
        by_stable[stable] = r.chunk_text
    return {"by_uuid": by_uuid, "by_stable": by_stable}


def check_labels_match_corpus(questions: list[dict], corpus: dict) -> None:
    """Fail fast if the DB was re-chunked since questions.csv was labeled; otherwise
    recall@5 would silently compare against chunk ids that no longer mean the same text."""
    problems = []
    for q in questions:
        if not q["in_scope"]:
            continue
        missing = [c for c in q["gold_ids"] if c not in corpus["by_stable"]]
        if missing:
            problems.append(f"{q['id']}: chunk ids not in DB: {missing}")
        elif q["evidence_quote"] not in corpus["by_stable"][q["gold_ids"][0]]:
            problems.append(f"{q['id']}: evidence_quote no longer in {q['gold_ids'][0]}")
    if problems:
        sys.exit("questions.csv does not match the ingested corpus:\n  " + "\n  ".join(problems))


# --------------------------------------------------------------------------
# LLM calls
# --------------------------------------------------------------------------
async def _post_json(client, url: str, payload: dict, headers: dict | None = None,
                     retries: int = 8) -> dict:
    import httpx

    for attempt in range(retries):
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TransportError:
            if attempt == retries - 1:
                raise
        else:
            if resp.status_code not in _RETRYABLE or attempt == retries - 1:
                resp.raise_for_status()
                data = resp.json()
                _record_usage(payload.get("model", ""), data)
                return data
        await asyncio.sleep(min(2 ** attempt, 30))  # ~2 min total before giving up
    raise RuntimeError("unreachable")


def _record_usage(model: str, data: dict) -> None:
    usage = data.get("usage")
    if not usage:  # Ollama responses have no usage block
        return
    u = USAGE.setdefault(model, Counter())
    u["calls"] += 1
    u["input"] += usage.get("prompt_tokens", 0)
    u["cached"] += (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    u["output"] += usage.get("completion_tokens", 0)


def print_usage() -> None:
    """Actual tokens billed this session (excludes questions reused via --resume)."""
    if not USAGE:
        return
    total = 0.0
    print("  Token usage this session:")
    for model, u in USAGE.items():
        line = (f"    {model:<12} {u['calls']:4} calls  {u['input']:>9,} in "
                f"({u['cached']:,} cached)  {u['output']:>8,} out")
        if model in PRICES:
            p_in, p_cached, p_out = PRICES[model]
            cost = ((u["input"] - u["cached"]) * p_in + u["cached"] * p_cached + u["output"] * p_out) / 1e6
            total += cost
            line += f"  ~${cost:.2f}"
        print(line)
    print(f"    estimated total ~${total:.2f}\n")


def answer_model_name(settings) -> str:
    if settings.llm_provider == "openai" and settings.openai_api_key:
        return f"openai:{APP_OPENAI_MODEL}"
    return f"ollama:{settings.ollama_model}"


async def call_app_llm(client, settings, messages: list[dict]) -> str:
    """Same provider, model, and params as generation.generate_response, except
    temperature 0. Applies the same fix_output_text post-processing."""
    from backend.services.generation import fix_output_text

    if settings.llm_provider == "openai" and settings.openai_api_key:
        data = await _post_json(
            client, "https://api.openai.com/v1/chat/completions",
            {"model": APP_OPENAI_MODEL, "messages": messages, "temperature": 0,
             "max_tokens": 800, "seed": 0},
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        )
        answer = data["choices"][0]["message"]["content"]
    else:
        data = await _post_json(
            client, f"{settings.ollama_host}/api/chat",
            {"model": settings.ollama_model, "messages": messages, "stream": False,
             "options": {"temperature": 0, "top_p": 0.9, "num_predict": 1024, "seed": 0}},
        )
        answer = data.get("message", {}).get("content", "")
    return fix_output_text(answer)


# --------------------------------------------------------------------------
# The two arms
# --------------------------------------------------------------------------
_CONTEXT_MARKER = "\n\nMEDICAL CONTEXT"


def rag_off_messages(question: str) -> list[dict]:
    """The app's exact system prompt and patient line, with the context block removed."""
    from backend.services.generation import build_prompt

    messages = build_prompt(question, [], EVAL_PATIENT, [])
    system = messages[0]["content"]
    assert _CONTEXT_MARKER in system, "build_prompt format changed; update rag_off_messages"
    messages[0]["content"] = system.split(_CONTEXT_MARKER)[0]
    return messages


async def rag_on_answer(client, settings, db, question: str) -> dict:
    """Mirrors routers/chat.py::chat_query for a single-turn conversation."""
    from backend.services.clarification import detect_ambiguity
    from backend.services.retrieval import search_chunks
    from backend.services.evaluation import should_refuse
    from backend.services.generation import build_prompt
    from backend.routers.chat import fix_broken_words

    ambiguity = detect_ambiguity(question)
    if ambiguity["is_ambiguous"]:
        return {"answer": ambiguity["followup_question"], "path": "clarification", "chunks": []}
    # NOTE: this mirrors chat_query step by step; if you change the router, change this too.

    from backend.services.generation import NO_SOURCE_MESSAGE

    chunks = search_chunks(db, question, age_range="pediatric")
    if should_refuse(chunks):
        return {"answer": NO_SOURCE_MESSAGE, "path": "no_source_decline", "chunks": chunks}
    messages = build_prompt(question, chunks, EVAL_PATIENT, [])
    answer = fix_broken_words(await call_app_llm(client, settings, messages))
    return {"answer": answer, "path": "grounded", "chunks": chunks}


# --------------------------------------------------------------------------
# Retrieval recall
# --------------------------------------------------------------------------
def recall_at_k(retrieved_ids: list[str], gold_ids: list[str], k: int = TOP_K_FOR_RECALL) -> int:
    """1 if any gold chunk is among the top-k retrieved, else 0. (With one relevant chunk
    per question this is also called hit rate@k.)"""
    return int(bool(set(retrieved_ids[:k]) & set(gold_ids)))


# --------------------------------------------------------------------------
# Judge
# --------------------------------------------------------------------------
JUDGE_SYSTEM = """You are a strict medical fact-checker grading a pediatric chatbot's answer.

You get: the parent's question, whether the question is covered by the chatbot's source
documents, a reference answer (if covered), SOURCE EXCERPTS from the chatbot's document
corpus (each tagged with a chunk id), and finally the chatbot's ANSWER.

Step 1 - List every MEDICAL CLAIM in the ANSWER. A medical claim is any specific
statement about symptoms, causes, diagnosis, thresholds, ages, timing, durations,
treatments, medications, doses, side effects, prevention, prognosis, or specific criteria
for when to seek care. These are NOT medical claims (skip them): empathy, restating the
question, generic advice to contact a pediatrician/doctor with no specific criteria,
generic monitoring or comfort advice with no specific medical content (e.g. "keep an eye on
how they're doing", "make sure they rest", "trust your instincts"), bare instructions to call
emergency services ("Call 911 right now.", "Call Poison Control at 1-800-222-1222 right
now." - never list these as claims), source citations like "[S1]", and statements that the
chatbot cannot answer.
Anything naming specific signs, amounts, timings, or treatments IS a claim (e.g. "watch for
dry mouth and fewer wet diapers" is a claim).

Step 2 - For each claim, check it against the SOURCE EXCERPTS ONLY, never your own
knowledge. Status:
  "supported"    - an excerpt states it or directly implies it (paraphrase is fine)
  "not_found"    - no excerpt says it, even if it is true in the real world, or the claim
                   adds specifics (numbers, ages, drug names) that no excerpt contains
  "contradicted" - an excerpt says something incompatible with it
Cite the chunk ids you relied on.

Step 3 - "declined": true if the answer says it cannot answer, does not have the
information, or only refers the parent elsewhere without answering the question.

Step 4 - "matches_reference": for covered questions, true if the answer conveys the key
facts of the reference answer (paraphrase is fine) and does not contradict it. For
questions not covered, use null.

Return JSON only:
{"claims": [{"claim": "short paraphrase", "status": "supported|not_found|contradicted", "chunk_ids": ["..."]}],
 "declined": true|false,
 "matches_reference": true|false|null,
 "reasoning": "1-3 sentences explaining the grade, naming any unsupported claim"}"""


def _answer_sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", answer or "")
    return [p.strip(" -*#") for p in parts if len(p.strip(" -*#")) >= 25]


def evidence_pool(db, answers: list[str], gold_ids: list[str], retrieved_ids: list[str],
                  corpus: dict, max_chunks: int = MAX_EVIDENCE_CHUNKS) -> list[str]:
    """Source excerpts the judge checks claims against, as stable chunk ids.

    The corpus is too large to hand the judge whole. One pool is built per question and
    shared by BOTH arms, so both answers are graded against identical evidence. It is
    filled in priority order until max_chunks:
      1. gold chunks
      2. RAG-on's top-5 retrieved chunks
      3. the nearest corpus chunk to each sentence of either answer (sentences from the
         two answers alternate, so neither arm crowds out the other)
      4. the rest of RAG-on's retrieved chunks
      5. the second-nearest chunk to each sentence
    Step 3 is what makes this a check against the whole corpus rather than only the
    chunks retrieval happened to find."""
    from itertools import chain, zip_longest

    from sqlalchemy import text
    from backend.utils.embeddings import get_embedding_model

    per_answer = [_answer_sentences(a) for a in answers]
    sentences = [s for s in chain.from_iterable(zip_longest(*per_answer)) if s]
    nearest, second = [], []
    if sentences:
        vectors = get_embedding_model().encode(sentences, normalize_embeddings=True)
        sql = text("SELECT id FROM chunks ORDER BY embedding <=> CAST(:e AS vector) LIMIT :k")
        for v in vectors:
            ids = [corpus["by_uuid"][str(r.id)]
                   for r in db.execute(sql, {"e": str(v.tolist()), "k": EVIDENCE_PER_SENTENCE})]
            nearest += ids[:1]
            second += ids[1:]
    ordered = gold_ids + retrieved_ids[:TOP_K_FOR_RECALL] + nearest + retrieved_ids[TOP_K_FOR_RECALL:] + second
    return list(dict.fromkeys(ordered))[:max_chunks]


async def judge_answer(client, settings, judge_model: str, q: dict, answer: str,
                       pool: list[str], corpus: dict) -> dict:
    # The answer goes LAST. Both arms of a question share everything before it, so
    # OpenAI's automatic prompt caching bills that prefix at half price on the 2nd call.
    excerpts = "\n\n".join(f"[{cid}]\n{corpus['by_stable'][cid]}" for cid in pool)
    user = (
        f"QUESTION: {q['question']}\n"
        f"COVERED BY SOURCES: {'yes' if q['in_scope'] else 'no'}\n"
        f"REFERENCE ANSWER: {q['reference_answer'] or '(none - not covered by the sources)'}\n\n"
        f"SOURCE EXCERPTS:\n{excerpts}\n\nANSWER:\n{answer}"
    )
    # max_tokens matters for rate limits: OpenAI counts the maximum possible output against
    # the tokens-per-minute budget, and gpt-4o's is low (30k/min on this account).
    payload = {"model": judge_model, "temperature": 0, "seed": 0, "max_tokens": 1500,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": JUDGE_SYSTEM},
                            {"role": "user", "content": user}]}
    headers = {"Authorization": f"Bearer {settings.openai_api_key}"}

    for _ in range(2):  # one retry on malformed JSON
        data = await _post_json(client, "https://api.openai.com/v1/chat/completions",
                                payload, headers=headers)
        try:
            out = json.loads(data["choices"][0]["message"]["content"])
            claims = out["claims"]
            out["verdict"] = final_verdict(claims, bool(out["declined"]),
                                           out.get("matches_reference"), q["in_scope"])
            out["evidence_ids"] = pool
            return out
        except (json.JSONDecodeError, KeyError, TypeError):
            continue
    return {"verdict": "JudgeError", "claims": [], "reasoning": "judge returned invalid JSON",
            "evidence_ids": pool}


_EMERGENCY_REFERRAL = re.compile(
    r"(please )?(call|dial|contact) (911|988|poison control|emergency services)"
    r"( at [\d\s()-]+)?( (right )?(now|away)| immediately)?")


def _is_emergency_referral(claim: str) -> bool:
    """True for a bare 'call 911 / Poison Control' instruction, which the rubric exempts.
    Enforced in code because the judge sometimes lists them anyway. 'Call 911 if the
    seizure lasts more than 5 minutes' is NOT exempt: the criterion is a medical claim."""
    text = re.sub(r"[^a-z0-9()\s-]", " ", (claim or "").lower())
    return bool(_EMERGENCY_REFERRAL.fullmatch(" ".join(text.split())))


def final_verdict(claims: list[dict], declined: bool, matches_reference, in_scope: bool) -> str:
    """Deterministic label from the judge's structured output. Order matters: one
    unsupported claim outweighs everything else, including a partial decline."""
    claims = [c for c in claims if not _is_emergency_referral(c.get("claim", ""))]
    if any(c.get("status") in ("not_found", "contradicted") for c in claims):
        return "Unsupported"
    if declined:
        return "Declined"
    if in_scope and matches_reference is True:
        return "Correct"
    return "Incomplete"


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
def canned_no_source_message() -> str | None:
    """The app's fixed 'no verified source' reply, if the app defines one."""
    from backend.services import generation
    return getattr(generation, "NO_SOURCE_MESSAGE", None)


def canned_verdict(pool: list[str]) -> dict:
    """The fixed reply contains no medical claims, so it is Declined by definition; no
    judge call needed."""
    return {"verdict": "Declined", "claims": [], "declined": True, "matches_reference": None,
            "reasoning": "Fixed no-source reply; contains no medical claims.", "evidence_ids": pool}


async def evaluate_question(client, settings, db, corpus, judge_model, q, max_evidence,
                            arms: tuple[str, ...] = ("rag_off", "rag_on")) -> dict:
    off_answer = None
    if "rag_off" in arms:
        off_answer = await call_app_llm(client, settings, rag_off_messages(q["question"]))
    on = await rag_on_answer(client, settings, db, q["question"])

    retrieved_ids = [corpus["by_uuid"][c["id"]] for c in on["chunks"]]
    record = {
        "id": q["id"],
        "rag_off_answer": off_answer,
        "rag_on_answer": on["answer"],
        "rag_on_pipeline_path": on["path"],
        "rag_on_top5_chunk_ids": retrieved_ids[:TOP_K_FOR_RECALL],
        "rag_on_top5_similarities": [round(c["similarity"], 3) for c in on["chunks"][:TOP_K_FOR_RECALL]],
        "rag_on_recall_at_5": recall_at_k(retrieved_ids, q["gold_ids"]) if q["in_scope"] else None,
        "rag_off_judge": None,
    }
    answers = [a for a in (off_answer, on["answer"]) if a is not None]
    pool = evidence_pool(db, answers, q["gold_ids"], retrieved_ids, corpus, max_evidence)
    canned = canned_no_source_message()
    for arm in arms:  # sequential, so the 2nd call can hit the prompt cache
        answer = record[f"{arm}_answer"]
        if canned and answer.strip() == canned.strip():
            record[f"{arm}_judge"] = canned_verdict(pool)
        else:
            record[f"{arm}_judge"] = await judge_answer(
                client, settings, judge_model, q, answer, pool, corpus)
    return record


def _load_cache(config: dict) -> dict:
    done = {}
    if CACHE_JSONL.exists():
        for line in CACHE_JSONL.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("config") == config:
                done[rec["id"]] = rec
    return done


async def run_all(questions, judge_model: str, resume: bool,
                  max_evidence: int = MAX_EVIDENCE_CHUNKS,
                  arms: tuple[str, ...] = ("rag_off", "rag_on"),
                  concurrency: int = 1) -> tuple[list[dict], dict]:
    import httpx
    from backend.config import get_settings
    from backend.models.database import SessionLocal

    settings = get_settings()
    if not settings.openai_api_key:
        sys.exit("The judge needs OPENAI_API_KEY (it uses the OpenAI API regardless of LLM_PROVIDER).")
    config = {"answer_model": answer_model_name(settings), "judge_model": judge_model,
              "max_evidence": max_evidence, "arms": list(arms),
              "similarity_threshold": settings.similarity_threshold}

    db = SessionLocal()
    try:
        corpus = load_corpus(db)
        check_labels_match_corpus(questions, corpus)
        done = _load_cache(config) if resume else {}
        if not resume:
            CACHE_JSONL.unlink(missing_ok=True)

        print(f"Answer model: {config['answer_model']} (temperature 0)   Judge: {judge_model}   "
              f"Arms: {', '.join(arms)}   Cutoff: {settings.similarity_threshold}", flush=True)
        print(f"Corpus: {len(corpus['by_stable'])} chunks   Questions: {len(questions)}   "
              f"Already done: {len(done)}\n", flush=True)

        # Questions run concurrently; the DB and embedding calls inside are synchronous and
        # never yield mid-call, so the single session is only ever used by one at a time.
        sem = asyncio.Semaphore(max(1, concurrency))
        finished = 0

        async def one(client, q):
            nonlocal finished
            if q["id"] in done:
                return done[q["id"]]
            async with sem:
                rec = await evaluate_question(client, settings, db, corpus, judge_model, q,
                                              max_evidence, arms)
            rec["config"] = config
            with open(CACHE_JSONL, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            finished += 1
            off = (rec["rag_off_judge"] or {}).get("verdict", "-")
            print(f"[{finished:2}/{len(questions) - len(done)}] {q['id']}  off={off:<11} "
                  f"on={rec['rag_on_judge']['verdict']:<11} recall@5={rec['rag_on_recall_at_5']}  "
                  f"{q['question'][:50]}", flush=True)
            return rec

        async with httpx.AsyncClient(timeout=120.0) as client:
            records = await asyncio.gather(*(one(client, q) for q in questions))
        return list(records), corpus["by_stable"]
    finally:
        db.close()


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------
RESULT_FIELDS = [
    "id", "question", "in_scope", "source_document", "supporting_chunk_ids", "reference_answer",
    "rag_off_answer", "rag_off_verdict", "rag_off_judge_reasoning", "rag_off_claims",
    "rag_off_hand_check_id",
    "rag_on_answer", "rag_on_verdict", "rag_on_judge_reasoning", "rag_on_claims",
    "rag_on_hand_check_id",
    "rag_on_pipeline_path", "rag_on_top5_chunk_ids", "rag_on_top5_similarities",
    "rag_on_recall_at_5", "answer_model", "judge_model",
]


def assign_hand_check_ids(records: list[dict], seed: int) -> dict:
    """Pick HAND_CHECK_N random (question, arm) answers. Returns {(id, arm): 'H01', ...}."""
    pairs = [(r["id"], arm) for r in records for arm in ("rag_off", "rag_on")
             if r.get(f"{arm}_answer") is not None]
    sample = random.Random(seed).sample(pairs, min(HAND_CHECK_N, len(pairs)))
    return {pair: f"H{i:02d}" for i, pair in enumerate(sample, 1)}


def write_results(questions, records, hand_ids: dict) -> None:
    by_id = {q["id"]: q for q in questions}
    with open(RESULTS_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=RESULT_FIELDS)
        w.writeheader()
        for rec in records:
            q = by_id[rec["id"]]
            row = {
                "id": q["id"], "question": q["question"],
                "in_scope": "yes" if q["in_scope"] else "no",
                "source_document": q["source_document"],
                "supporting_chunk_ids": q["supporting_chunk_ids"],
                "reference_answer": q["reference_answer"],
                "rag_on_pipeline_path": rec["rag_on_pipeline_path"],
                "rag_on_top5_chunk_ids": ";".join(rec["rag_on_top5_chunk_ids"]),
                "rag_on_top5_similarities": ";".join(map(str, rec["rag_on_top5_similarities"])),
                "rag_on_recall_at_5": "" if rec["rag_on_recall_at_5"] is None else rec["rag_on_recall_at_5"],
                "answer_model": rec["config"]["answer_model"],
                "judge_model": rec["config"]["judge_model"],
            }
            for arm in ("rag_off", "rag_on"):
                j = rec.get(f"{arm}_judge")
                if j is None:  # arm not run (--arms on)
                    continue
                row[f"{arm}_answer"] = rec[f"{arm}_answer"]
                row[f"{arm}_verdict"] = j["verdict"]
                row[f"{arm}_judge_reasoning"] = j.get("reasoning", "")
                row[f"{arm}_claims"] = json.dumps(
                    {"claims": j.get("claims", []), "declined": j.get("declined"),
                     "matches_reference": j.get("matches_reference"),
                     "evidence_ids": j.get("evidence_ids", [])}, ensure_ascii=False)
                row[f"{arm}_hand_check_id"] = hand_ids.get((rec["id"], arm), "")
            w.writerow(row)


def write_hand_check(questions, records, hand_ids: dict, corpus_text: dict) -> None:
    """Blind: no arm and no judge verdict, so your grade isn't anchored to either.
    The key linking H-ids back to arm + judge verdict lives in results.csv.
    Refuses to overwrite a file you have already started grading."""
    if HAND_CHECK_CSV.exists():
        with open(HAND_CHECK_CSV, newline="", encoding="utf-8") as fh:
            if any(r.get("your_verdict", "").strip() for r in csv.DictReader(fh)):
                print(f"  {HAND_CHECK_CSV.name} already has your grades; not overwriting it.")
                return
    by_id = {q["id"]: q for q in questions}
    rec_by_id = {r["id"]: r for r in records}
    rows = []
    for (qid, arm), hid in sorted(hand_ids.items(), key=lambda kv: kv[1]):
        q = by_id[qid]
        sources = "\n\n".join(f"[{c}]\n{corpus_text.get(c, '')}" for c in q["gold_ids"]) \
            or "Out of scope: none of the 12 source documents cover this topic."
        rows.append({
            "hand_check_id": hid, "question_id": qid, "question": q["question"],
            "in_scope": "yes" if q["in_scope"] else "no",
            "reference_answer": q["reference_answer"], "source_excerpts": sources,
            "answer": rec_by_id[qid][f"{arm}_answer"],
            "your_verdict": "", "your_notes": "",
        })
    with open(HAND_CHECK_CSV, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% confidence interval for a proportion; behaves well at small n and near 0/100%."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _rate(rows: list[dict], col: str, value: str) -> str:
    rows = [r for r in rows if r[col]]  # skip arms that weren't run
    n = len(rows)
    k = sum(1 for r in rows if r[col] == value)
    lo, hi = wilson_interval(k, n)
    return f"{100 * k / n:5.1f}% [{100 * lo:3.0f}-{100 * hi:3.0f}]" if n else "-"


def print_summary(results_path: Path | None = None) -> None:
    with open(results_path or RESULTS_CSV, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    ins = [r for r in rows if r["in_scope"] == "yes"]
    oos = [r for r in rows if r["in_scope"] == "no"]

    lines = [
        (f"Correct            (answerable, n={len(ins)})", "Correct", ins),
        (f"Unsupported        (all, n={len(rows)})", "Unsupported", rows),
        (f"Unsupported        (answerable, n={len(ins)})", "Unsupported", ins),
        (f"Unsupported        (out of scope, n={len(oos)})", "Unsupported", oos),
        (f"Declined           (out of scope, n={len(oos)})", "Declined", oos),
        (f"Declined           (answerable, n={len(ins)})", "Declined", ins),
        (f"Incomplete         (answerable, n={len(ins)})", "Incomplete", ins),
    ]
    width = 44
    print("\n" + "=" * 90)
    print(f"  RAG OFF vs RAG ON   answer model: {rows[0]['answer_model']}   judge: {rows[0]['judge_model']}")
    print("  percentages with 95% Wilson confidence intervals")
    print("=" * 90)
    print(f"  {'metric':<{width}}{'RAG off':<22}{'RAG on':<22}")
    print("  " + "-" * 86)
    for label, value, subset in lines:
        print(f"  {label:<{width}}{_rate(subset, 'rag_off_verdict', value):<22}"
              f"{_rate(subset, 'rag_on_verdict', value):<22}")
    hits = [int(r["rag_on_recall_at_5"]) for r in ins if r["rag_on_recall_at_5"] != ""]
    lo, hi = wilson_interval(sum(hits), len(hits))
    recall = f"{100 * sum(hits) / len(hits):5.1f}% [{100 * lo:3.0f}-{100 * hi:3.0f}]" if hits else "n/a"
    print(f"  {f'Retrieval recall@5 (answerable, n={len(hits)})':<{width}}{'-':<22}{recall:<22}")

    paths = Counter(r["rag_on_pipeline_path"] for r in rows)
    print(f"\n  RAG-on pipeline paths: {dict(paths)}")
    errors = sum(r[f"{a}_verdict"] == "JudgeError" for r in rows for a in ("rag_off", "rag_on"))
    if errors:
        print(f"  WARNING: {errors} answers could not be graded (JudgeError); re-run with --resume.")
    print()


# --------------------------------------------------------------------------
# Judge vs. human agreement
# --------------------------------------------------------------------------
def _normalize_label(s: str) -> str | None:
    """Accept 'Correct', 'correct', or just 'c' (likewise u / d / i)."""
    s = (s or "").strip().lower()
    return next((v for v in VERDICTS if s and v.lower().startswith(s)), None)


def cohens_kappa(a: list[str], b: list[str]) -> float:
    """Agreement corrected for the agreement you'd expect by chance (1 = perfect, 0 = chance)."""
    n = len(a)
    if n == 0:
        return float("nan")
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(a) | set(b)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def _print_confusion(rows_labels: list[str], col_labels: list[str], corner: str) -> None:
    print(f"\n  {corner:<16}" + "".join(f"{v:<13}" for v in VERDICTS))
    for a in VERDICTS:
        counts = [sum(1 for x, y in zip(rows_labels, col_labels) if x == a and y == b)
                  for b in VERDICTS]
        print(f"  {a:<16}" + "".join(f"{c:<13}" for c in counts))


async def _rejudge_all(rows, judge_model: str, concurrency: int, sample: int | None = None,
                       seed: int = 42) -> list[dict]:
    import httpx
    from backend.config import get_settings
    from backend.models.database import SessionLocal

    settings = get_settings()
    questions = {q["id"]: q for q in load_questions()}
    db = SessionLocal()
    try:
        corpus = load_corpus(db)
    finally:
        db.close()
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(client, row, arm):
        claims = json.loads(row[f"{arm}_claims"])
        if not claims.get("claims") and row[f"{arm}_verdict"] == "Declined" \
                and claims.get("declined") and row[f"{arm}_judge_reasoning"].startswith("Fixed"):
            return canned_verdict(claims.get("evidence_ids", []))
        async with sem:
            return await judge_answer(client, settings, judge_model, questions[row["id"]],
                                      row[f"{arm}_answer"], claims.get("evidence_ids", []), corpus)

    async with httpx.AsyncClient(timeout=120.0) as client:
        jobs = [(row, arm) for row in rows for arm in ("rag_off", "rag_on") if row[f"{arm}_verdict"]]
        if sample and sample < len(jobs):  # a random subset keeps a strong-judge check cheap
            jobs = random.Random(seed).sample(jobs, sample)
        judged = await asyncio.gather(*(one(client, r, a) for r, a in jobs))
    return [(row["id"], arm, row[f"{arm}_verdict"], j) for (row, arm), j in zip(jobs, judged)]


def rejudge(path: Path, judge_model: str, concurrency: int, sample: int | None = None) -> None:
    """Grade the SAME answers (and the same evidence) with another judge, to measure how
    far the cheap iteration judge can be trusted. With `sample`, only a random subset is
    re-graded and the written CSV keeps the original verdict for the rest."""
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    results = asyncio.run(_rejudge_all(rows, judge_model, concurrency, sample))
    old = [r[2] for r in results]
    new = [r[3]["verdict"] for r in results]
    agree = sum(a == b for a, b in zip(old, new))
    print(f"\nRe-judged {len(results)} answers from {path.name} with {judge_model}.")
    print(f"Agreement with original judge ({rows[0]['judge_model']}): {agree}/{len(results)} "
          f"({100 * agree / len(results):.0f}%), Cohen's kappa = {cohens_kappa(old, new):.2f}")
    _print_confusion(old, new, "original \\ new")

    by_key = {(qid, arm): j for qid, arm, _, j in results}
    for row in rows:
        for arm in ("rag_off", "rag_on"):
            j = by_key.get((row["id"], arm))
            if j is None:
                continue
            row[f"{arm}_verdict"] = j["verdict"]
            row[f"{arm}_judge_reasoning"] = j.get("reasoning", "")
            row[f"{arm}_claims"] = json.dumps(
                {"claims": j.get("claims", []), "declined": j.get("declined"),
                 "matches_reference": j.get("matches_reference"),
                 "evidence_ids": j.get("evidence_ids", [])}, ensure_ascii=False)
        row["judge_model"] = judge_model
    out = path.with_name(path.stem + f"_rejudged_{judge_model}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nWrote {out.name}")
    print_summary(out)
    print_usage()


def compare_hand_check() -> None:
    with open(RESULTS_CSV, newline="", encoding="utf-8") as fh:
        results = list(csv.DictReader(fh))
    judge = {}
    for r in results:
        for arm in ("rag_off", "rag_on"):
            if r[f"{arm}_hand_check_id"]:
                judge[r[f"{arm}_hand_check_id"]] = (r[f"{arm}_verdict"], arm)
    with open(HAND_CHECK_CSV, newline="", encoding="utf-8") as fh:
        hand = list(csv.DictReader(fh))

    pairs, skipped = [], []
    for h in hand:
        mine = _normalize_label(h["your_verdict"])
        if mine is None:
            skipped.append(h["hand_check_id"])
            continue
        pairs.append((h["hand_check_id"], mine, *judge[h["hand_check_id"]]))
    if not pairs:
        sys.exit(f"No graded rows in {HAND_CHECK_CSV}. Fill `your_verdict` with one of {VERDICTS}.")

    agree = sum(p[1] == p[2] for p in pairs)
    print(f"\nJudge vs. you on {len(pairs)} answers: {agree}/{len(pairs)} agree "
          f"({100 * agree / len(pairs):.0f}%), Cohen's kappa = "
          f"{cohens_kappa([p[1] for p in pairs], [p[2] for p in pairs]):.2f}")
    if skipped:
        print(f"Skipped (no valid your_verdict): {', '.join(skipped)}")
    _print_confusion([p[1] for p in pairs], [p[2] for p in pairs], "you \\ judge")
    print("\nDisagreements:")
    for hid, mine, theirs, arm in pairs:
        if mine != theirs:
            print(f"  {hid} ({arm}): you={mine}, judge={theirs}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG on vs. off eval with an LLM judge.")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL,
                        help="OpenAI model for grading; use one stronger than the answer model")
    parser.add_argument("--max-evidence", type=int, default=MAX_EVIDENCE_CHUNKS,
                        help="source chunks shown to the judge per question (main cost driver)")
    parser.add_argument("--limit", type=int, help="only run the first N questions (smoke test)")
    parser.add_argument("--resume", action="store_true",
                        help="reuse finished questions from results_cache.jsonl")
    parser.add_argument("--seed", type=int, default=42, help="seed for the hand-check sample")
    parser.add_argument("--summary-only", action="store_true", help="re-print table from results.csv")
    parser.add_argument("--compare-hand-check", action="store_true",
                        help="compare your grades in hand_check.csv with the judge")
    parser.add_argument("--arms", choices=["both", "on"], default="both",
                        help="'on' skips the RAG-off arm (it doesn't change when the app does)")
    parser.add_argument("--concurrency", type=int, default=1, help="questions evaluated in parallel")
    parser.add_argument("--tag", help="write eval/runs/<tag>_results.csv etc. instead of results.csv")
    parser.add_argument("--rejudge", type=Path,
                        help="re-grade the answers in this results CSV with --judge-model")
    parser.add_argument("--sample", type=int, help="with --rejudge: only re-grade N random answers")
    args = parser.parse_args()

    global RESULTS_CSV, HAND_CHECK_CSV, CACHE_JSONL
    if args.tag:
        RUNS_DIR.mkdir(exist_ok=True)
        RESULTS_CSV = RUNS_DIR / f"{args.tag}_results.csv"
        HAND_CHECK_CSV = RUNS_DIR / f"{args.tag}_hand_check.csv"
        CACHE_JSONL = RUNS_DIR / f"{args.tag}_cache.jsonl"

    if args.summary_only:
        return print_summary()
    if args.compare_hand_check:
        return compare_hand_check()
    if args.rejudge:
        return rejudge(args.rejudge, args.judge_model, args.concurrency, args.sample)

    questions = load_questions()
    if args.limit:
        questions = questions[:args.limit]
    arms = ("rag_on",) if args.arms == "on" else ("rag_off", "rag_on")
    records, corpus_text = asyncio.run(
        run_all(questions, args.judge_model, args.resume, args.max_evidence, arms,
                args.concurrency))

    hand_ids = assign_hand_check_ids(records, args.seed)
    write_results(questions, records, hand_ids)
    write_hand_check(questions, records, hand_ids, corpus_text)
    print_summary()
    print_usage()
    print(f"Wrote {RESULTS_CSV.name} ({len(records)} questions) and "
          f"{HAND_CHECK_CSV.name} ({len(hand_ids)} answers to grade).")


if __name__ == "__main__":
    main()
