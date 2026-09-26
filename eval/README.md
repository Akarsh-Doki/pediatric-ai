# RAG Evaluation Harness (Tier 1 build — feature #7)

This folder measures how well retrieval and answers actually perform, so claims about
quality are grounded in numbers you measured rather than asserted. Everything here is
deterministic and computed at run time — **no metric values are hardcoded anywhere.**

## What's here

| File | Purpose |
| --- | --- |
| `questions.csv` | 80 questions: 60 answerable from the 12 source PDFs (with source doc, supporting chunk ids, a verbatim evidence quote, and a reference answer) and 20 on topics no source covers. |
| `run_eval.py` | **RAG on vs. RAG off.** Answers every question twice with the app's model at temperature 0, grades each answer with an LLM judge that checks every medical claim against the corpus, computes retrieval recall@5, and writes `results.csv` + `hand_check.csv`. |
| `retrieval_eval.py` | Retrieval-only harness: **dense vs. hybrid** precision/recall/MRR over `testset.jsonl`. |
| `metrics.py` | Pure IR + grounding metrics: `precision@k`, `recall@k`, MRR, grounding/hallucination rate, calibration buckets + ECE. Fully unit-tested. |
| `../backend/services/hybrid_retrieval.py` | TF-IDF (sparse) + vector (dense) fusion reranker, now used by the app (`RETRIEVAL_MODE=hybrid`, the default). Moved out of `eval/` after Run 4 showed it helps. |
| `testset.jsonl` | Labeled questions for `retrieval_eval.py`. Ships with **placeholder** gold labels you must fill in. |

## RAG on vs. off (`run_eval.py`)

From the repo root, with the database up and `OPENAI_API_KEY` set (the judge always uses
OpenAI; answers use whatever `LLM_PROVIDER` the app is configured for):

```bash
python -m eval.run_eval --limit 3            # smoke test first
python -m eval.run_eval                      # full run (~80 x 4 LLM calls)
python -m eval.run_eval --resume             # continue after a crash
python -m eval.run_eval --summary-only       # re-print the table
python -m eval.run_eval --compare-hand-check # after filling your_verdict in hand_check.csv
```

**Chunk ids** are `<pdf filename>#<chunk_index>` (e.g. `fever-guide.pdf#2`), not the DB
UUIDs, which change on every re-ingest. The run aborts if a labeled chunk id is missing
from the DB or its evidence quote is no longer in that chunk's text. If you change the
chunking or the PDFs, relabel `questions.csv`.

**Verdicts** are computed in code from the judge's per-claim output, in this order:
Unsupported (any claim not in the sources or contradicting them) → Declined → Correct
(matches the reference answer) → Incomplete (all claims supported, but doesn't answer the
question). The judge checks claims against one evidence set per question, shared by both
arms: gold chunks, then RAG-on's top 5, then the nearest corpus chunk to each sentence of
either answer, and so on, capped at `--max-evidence` (default 16).

**Cost:** about $3 per full run with `gpt-4o-mini` answers and a `gpt-4o` judge. The judge
input is ~90% of it. Each judge prompt puts the answer last, so the second call per
question reuses the first call's prefix through OpenAI's automatic prompt caching (billed
at half price). The script prints actual token usage and estimated cost at the end.

**Hand check:** `hand_check.csv` holds 25 randomly sampled answers with the arm and the
judge verdict hidden, so your grade isn't anchored. Fill `your_verdict` (Correct /
Unsupported / Declined / Incomplete, or just the first letter), then run
`--compare-hand-check` to get agreement % and Cohen's kappa.

## Dense vs. hybrid retrieval (`retrieval_eval.py`)

From the repo root, with the database reachable and the embedding model available
(same environment the API runs in):

```bash
python -m eval.retrieval_eval                  # k=5, hybrid alpha=0.6
python -m eval.retrieval_eval --k 3 --alpha 0.5
python -m eval.retrieval_eval --grounding      # also measures answer grounding (calls the LLM)
```

Results print to the console and are written to `eval/last_retrieval_results.json`.

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
If no rows are labeled, `retrieval_eval` says so and reports zero labeled rows instead of
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
