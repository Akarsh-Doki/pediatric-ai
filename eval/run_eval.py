"""
RAG evaluation harness  (TIER 3, feature #7).

Runs the LIVE retriever over a labeled test set and reports real retrieval quality —
dense-only (production) vs. the TF-IDF+vector hybrid reranker — using the metrics in
eval/metrics.py. NOTHING here is hardcoded: every number is measured at run time against
your database. If the test set has no gold labels filled in yet, the harness says so and
reports zero labeled rows rather than inventing results.

Run it inside the repo (DB reachable + embedding model available):

    python -m eval.run_eval                 # default k=5, hybrid alpha=0.6
    python -m eval.run_eval --k 3 --alpha 0.5
    python -m eval.run_eval --grounding     # also measure answer grounding (calls the LLM)

Evaluation is at the DOCUMENT-SOURCE level: a question's gold answer lives in one or more
source documents (the `source` value in guideline_docs). Fill each row's
`expected_sources` in eval/testset.jsonl with those source strings to enable
precision@k / recall@k / MRR. See eval/README.md.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from eval.metrics import precision_at_k, recall_at_k, reciprocal_rank, mean_reciprocal_rank
from eval.hybrid_retrieval import hybrid_rerank

_TESTSET = Path(__file__).resolve().parent / "testset.jsonl"
_PLACEHOLDER_PREFIXES = ("FILL_IN", "REPLACE_ME", "<FILL_IN")


def load_testset(path: Path = _TESTSET) -> list:
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _is_labeled(expected_sources) -> bool:
    srcs = [s for s in (expected_sources or [])]
    if not srcs:
        return False
    return not any(str(s).startswith(_PLACEHOLDER_PREFIXES) for s in srcs)


def _sources_in_order(chunks) -> list:
    """Rank-ordered, de-duplicated list of doc sources from retrieved chunks."""
    seen, ordered = set(), []
    for c in chunks:
        s = c.get("doc_source")
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


def evaluate_retrieval(db, testset: list, k: int = 5, alpha: float = 0.6,
                       candidate_pool: int = 10) -> dict:
    """For each labeled row, run dense-only and hybrid retrieval and compute per-query
    P@k, R@k, RR at the document-source level. Returns aggregates plus per-query rows."""
    from backend.services.retrieval import search_chunks

    dense_p, dense_r, dense_cases = [], [], []
    hyb_p, hyb_r, hyb_cases = [], [], []
    per_query = []
    labeled = 0

    for row in testset:
        if not _is_labeled(row.get("expected_sources")):
            continue
        labeled += 1
        q = row["question"]
        gold = set(row["expected_sources"])

        # Dense baseline: pull a candidate pool, then take the natural dense order.
        dense_chunks = search_chunks(db, q, top_k=candidate_pool)
        dense_sources = _sources_in_order(dense_chunks)

        # Hybrid: rerank the SAME candidate pool by fused dense+lexical score.
        hybrid_chunks = hybrid_rerank(q, dense_chunks, alpha=alpha)
        hybrid_sources = _sources_in_order(hybrid_chunks)

        dp = precision_at_k(dense_sources, gold, k)
        dr = recall_at_k(dense_sources, gold, k)
        drr = reciprocal_rank(dense_sources, gold)
        hp = precision_at_k(hybrid_sources, gold, k)
        hr = recall_at_k(hybrid_sources, gold, k)
        hrr = reciprocal_rank(hybrid_sources, gold)

        dense_p.append(dp); dense_r.append(dr); dense_cases.append((dense_sources, gold))
        hyb_p.append(hp); hyb_r.append(hr); hyb_cases.append((hybrid_sources, gold))
        per_query.append({
            "id": row.get("id"), "question": q,
            "dense": {"p_at_k": round(dp, 3), "r_at_k": round(dr, 3), "rr": round(drr, 3)},
            "hybrid": {"p_at_k": round(hp, 3), "r_at_k": round(hr, 3), "rr": round(hrr, 3)},
        })

    def _mean(xs):
        return round(sum(xs) / len(xs), 4) if xs else 0.0

    return {
        "k": k, "alpha": alpha, "labeled_rows": labeled, "total_rows": len(testset),
        "dense": {f"precision@{k}": _mean(dense_p), f"recall@{k}": _mean(dense_r),
                  "mrr": round(mean_reciprocal_rank(dense_cases), 4)},
        "hybrid": {f"precision@{k}": _mean(hyb_p), f"recall@{k}": _mean(hyb_r),
                   "mrr": round(mean_reciprocal_rank(hyb_cases), 4)},
        "per_query": per_query,
    }


def measure_grounding(db, testset: list, candidate_pool: int = 10) -> dict:
    """OPTIONAL: generate an answer per question and measure how grounded it is in the
    retrieved chunks (eval/metrics.grounding_score). Needs the LLM, so it's behind a flag.
    Requires no gold labels."""
    import asyncio
    from eval.metrics import grounding_score, hallucination_rate
    from backend.services.retrieval import search_chunks
    from backend.services.generation import build_prompt, generate_response

    neutral_patient = {"name": "Eval", "age": 5, "sex": "female", "weight_kg": 18,
                       "known_conditions": [], "medications": []}

    async def _answer(messages):
        return await generate_response(messages)

    scores, rows = [], []
    for row in testset:
        q = row["question"]
        chunks = search_chunks(db, q, top_k=candidate_pool)
        messages = build_prompt(q, chunks, neutral_patient, [])
        result = asyncio.run(_answer(messages))
        answer = result.get("answer", "")
        contexts = [c.get("chunk_text", "") for c in chunks]
        g = grounding_score(answer, contexts)
        scores.append(g)
        rows.append({"id": row.get("id"), "grounding": round(g, 3),
                     "hallucination": round(hallucination_rate(answer, contexts), 3)})
    mean_g = round(sum(scores) / len(scores), 4) if scores else 0.0
    return {"mean_grounding": mean_g, "per_query": rows}


def print_report(results: dict, grounding: dict = None) -> None:
    try:
        from tabulate import tabulate
        have_tab = True
    except ImportError:
        have_tab = False

    k = results["k"]
    print("\n" + "=" * 64)
    print(f"  RAG RETRIEVAL EVAL   (k={k}, hybrid alpha={results['alpha']})")
    print(f"  labeled rows: {results['labeled_rows']} / {results['total_rows']}")
    print("=" * 64)

    if results["labeled_rows"] == 0:
        print("\n  No gold labels found in the test set, so retrieval precision/recall/MRR")
        print("  cannot be computed. Fill each row's `expected_sources` in")
        print("  eval/testset.jsonl with the real `source` values from your corpus")
        print("  (see eval/README.md), then re-run.")
    else:
        headers = ["metric", "dense (prod)", "hybrid"]
        rows = []
        for key in [f"precision@{k}", f"recall@{k}", "mrr"]:
            rows.append([key, results["dense"][key], results["hybrid"][key]])
        if have_tab:
            print("\n" + tabulate(rows, headers=headers, tablefmt="github"))
        else:
            print("\n" + "  ".join(headers))
            for r in rows:
                print("  ".join(str(x) for x in r))

        print("\n  Per-query (dense -> hybrid reciprocal rank):")
        for pq in results["per_query"]:
            print(f"   [{pq['id']}] RR {pq['dense']['rr']} -> {pq['hybrid']['rr']}   {pq['question'][:60]}")

    if grounding is not None:
        print("\n" + "-" * 64)
        print(f"  ANSWER GROUNDING   mean grounding rate: {grounding['mean_grounding']}")
        print("  (fraction of answer sentences supported by retrieved context;")
        print("   lexical proxy — see eval/README.md for its limitations)")
        for pq in grounding["per_query"]:
            print(f"   [{pq['id']}] grounding {pq['grounding']}  hallucination {pq['hallucination']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Run the live RAG retrieval evaluation.")
    parser.add_argument("--k", type=int, default=5, help="cutoff k for precision@k / recall@k")
    parser.add_argument("--alpha", type=float, default=0.6,
                        help="dense weight for hybrid fusion (1.0=dense-only, 0.0=lexical-only)")
    parser.add_argument("--candidate-pool", type=int, default=10,
                        help="how many dense candidates to retrieve before reranking")
    parser.add_argument("--testset", type=str, default=str(_TESTSET))
    parser.add_argument("--grounding", action="store_true",
                        help="also measure answer grounding (calls the LLM)")
    args = parser.parse_args()

    # Imported here so --help works without a configured DB/env.
    from backend.models.database import SessionLocal

    testset = load_testset(Path(args.testset))
    db = SessionLocal()
    try:
        results = evaluate_retrieval(db, testset, k=args.k, alpha=args.alpha,
                                     candidate_pool=args.candidate_pool)
        grounding = measure_grounding(db, testset, args.candidate_pool) if args.grounding else None
    finally:
        db.close()

    print_report(results, grounding)
    out_path = Path(__file__).resolve().parent / "last_run_results.json"
    payload = {"results": results}
    if grounding is not None:
        payload["grounding"] = grounding
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"  Full results written to {out_path}")


if __name__ == "__main__":
    main()
