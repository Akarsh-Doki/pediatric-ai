# RAG Evaluation Harness (Tier 1 build — feature #7)

This folder measures how well retrieval and answers actually perform, so claims about
quality are grounded in numbers you measured rather than asserted. Everything here is
deterministic and computed at run time — **no metric values are hardcoded anywhere.**

## What's here

| File | Purpose |
| --- | --- |
| `metrics.py` | Pure IR + grounding metrics: `precision@k`, `recall@k`, MRR, grounding/hallucination rate, calibration buckets + ECE. Fully unit-tested. |
| `hybrid_retrieval.py` | TF-IDF (sparse) + vector (dense) fusion reranker — a no-download alternative to a cross-encoder. Pure fusion math + a `hybrid_rerank` that re-scores the dense candidate pool. |
| `run_eval.py` | Live harness: runs the real retriever over the test set and prints **dense vs. hybrid** retrieval quality. Optional `--grounding` mode generates answers and measures how grounded they are. |
| `testset.jsonl` | Labeled questions. Ships with realistic pediatric questions and **placeholder** gold labels you must fill in. |

## How to run

From the repo root, with the database reachable and the embedding model available
(same environment the API runs in):

```bash
python -m eval.run_eval                  # k=5, hybrid alpha=0.6
python -m eval.run_eval --k 3 --alpha 0.5
python -m eval.run_eval --grounding      # also measures answer grounding (calls the LLM)
```

Results print to the console and are written to `eval/last_run_results.json`.

## Filling in the test set

Evaluation is at the **document-source level**: a question's correct answer lives in one
or more source documents. Each row in `testset.jsonl` looks like:

```json
{"id": "q1", "question": "How much acetaminophen ...", "expected_sources": ["FILL_IN: ..."], "category": "fever_dosing", "notes": "..."}
```

Replace each `expected_sources` entry with the real `source` string(s) of the
document(s) that should answer the question. Those are the values stored in the
`guideline_docs.source` column — list them, e.g.:

```sql
SELECT DISTINCT source FROM guideline_docs;
```

Until a row's labels are filled, the harness treats it as **unlabeled** (any value
starting with `FILL_IN` / `REPLACE_ME` is ignored) and skips it for precision/recall/MRR.
If no rows are labeled, `run_eval` says so and reports zero labeled rows instead of
emitting misleading zeros.

## What the metrics mean

- **precision@k** — of the top-k retrieved sources, the fraction that are gold.
- **recall@k** — of the gold sources, the fraction that appear in the top-k.
- **MRR** — mean reciprocal rank of the first gold source (rewards ranking it high).
- **grounding rate** — fraction of an answer's sentences whose content words overlap the
  retrieved context (a deterministic lexical proxy; `1 − grounding = hallucination rate`).
- **ECE** — expected calibration error: how far the model's confidence is from its
  observed accuracy, sample-weighted across confidence buckets.

## Honest limitations

- **Grounding is a lexical proxy, not an LLM judge.** It rewards lexical overlap, so a
  correctly paraphrased sentence can read as "unsupported," and safety boilerplate
  ("call your pediatrician") that isn't in the medical chunks will count against the
  score. It is most useful as a **relative** dense-vs-hybrid / before-vs-after signal,
  not as an absolute truth measure.
- **Hybrid reranking operates on the dense candidate pool**, so it can reorder what dense
  retrieval surfaced but cannot recover a gold document dense retrieval never returned.
  Widen `--candidate-pool` to give it more to work with.
- The seed test set is small and meant as a starting point; add more labeled questions
  for statistically meaningful numbers.
