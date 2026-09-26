# Accuracy improvement log

One change per run; each run re-evaluates all 80 questions in `questions.csv` (60 answerable, 20 out of scope) on the RAG-on pipeline. Answers come from `gpt-4o-mini` at temperature 0 and are graded by `gpt-4.1-mini`. Per-run files are in `runs/`.

| Run | Change | Correct (60 answerable) | Declined (20 out of scope) | Wrongly declined (answerable) | Unsupported (all 80) | Recall@5 | Cost | Time |
|---|---|---|---|---|---|---|---|---|
| 0 | Baseline: current app. Judge fixed so "Call 911 / Poison Control" is exempt | 65.0% | 0% | 0% | 46.2% | 48.3% | $0.30* | 2 min |
| 1 | Source-only system prompt with [S1] citations | 55.0% | 100% | 21.7% | 12.5% | 48.3% | $0.11 | 24 s |
| 2 | Fixed "no verified source" reply, no LLM call, when no chunk passes the cutoff | 55.0% | 100% | 31.7% | 8.8% | 48.3% | $0.05 | 20 s |
| 3a | Cutoff 0.55 → 0.50 | 73.3% | 100% | 10.0% | 8.8% | 70.0% | $0.11 | 26 s |
| 3b | Cutoff 0.45 | 78.3% | 90% | 8.3% | 11.2% | 75.0% | $0.13 | 1.7 min |
| **3c** | **Cutoff 0.40 (kept)** | **78.3%** | **95%** | **5.0%** | **8.8%** | **78.3%** | $0.14 | 1.8 min |
| 3c′ | Same config rerun, to measure noise | 78.3% | 95% | 5.0% | 11.2% | 78.3% | $0.11 | 1.5 min |
| **4** | **Hybrid search: vector + TF-IDF rerank (kept)** | **83.3%** | **95%** | **3.3%** | **11.2%** | **83.3%** | $0.20 | 1.4 min |
| Final | New defaults, no overrides | **81.7%** | **95%** | **3.3%** | **8.8%** | **83.3%** | $0.11 | 1.4 min |

\*$0.10 for the run plus $0.20 to re-grade it with `gpt-4.1-mini`, the judge used for every later run. The total for all runs, including the checks, was about **$1.45**.

**Judge check.** `gpt-4o` re-graded 20 random answers from the final run and agreed with `gpt-4.1-mini` on all 20 ($0.15). `gpt-4o-mini` was tried first as the judge and dropped: it scored the same baseline answers at 27% correct because it ignored the rubric's exemptions for generic advice.

## What each run changed and why

- **Run 0.** The rubric already exempted emergency numbers, but the judge still flagged "Call 911 right now." The exemption is now also enforced in code (`_is_emergency_referral`). "Call 911 if the seizure lasts 5+ minutes" still counts as a claim, because the criterion is medical.
- **Run 1.** The old prompt told the model to "use your general pediatric knowledge," so it answered every out-of-scope question with unverified claims. The new prompt answers only from sources, follows them over general knowledge, cites [S#], and says when sources don't cover a question. Out-of-scope declines went from 0% to 100%, and unsupported answers from 46% to 13%. Correct fell 10 points because 12 answerable questions retrieved nothing above 0.55, and the model now correctly declines those. That drop is a retrieval problem, not a prompt problem.
- **Run 2.** Replaces the remaining "LLM with no sources" path with a fixed reply. Its answers can no longer be unsupported, and it's cheaper. This exposed the retrieval gap as wrong declines, which rose to 32%.
- **Run 3.** Before sweeping, `should_refuse` was changed to use the same cutoff as retrieval. It had a hardcoded 0.45 floor that never did anything at 0.55 and would have silently overridden a 0.40 cutoff. 0.40 ties 0.45 on correct and wins on every secondary metric, by 1–2 questions each. At 0.40 the fixed reply fires for only 1 of 80 questions, so out-of-scope declines now come from the prompt.
- **Run 4.** Pulls 20 vector candidates, fuses vector and TF-IDF scores 60/40, and keeps the top 10. Its retrieval changes are deterministic: 4 questions gained a correct chunk in the top 5 and 1 lost one. Answers improved by 3 net correct versus the rerun baseline, while a rerun with no changes moved 1 question each way. The gain is small and not statistically significant, but it's free and nothing got worse, so it was kept and moved to `backend/services/hybrid_retrieval.py`.

## Remaining errors worth fixing next

- **Q11 (rotavirus at 4 months)** and **Q13 (Tdap in a later pregnancy)** are still wrong, even though the right chunk is retrieved. The model misreads the flattened schedule table. Both are high-stakes.
- **Q80 (umbilical hernia, out of scope):** answered from general knowledge after retrieving unrelated infant-care and first-aid chunks at ~0.45 similarity. This is the cost of the lower cutoff: weak matches pass the gate, and only the prompt stops the model.
- **Q40:** gives 100.4°F instead of the source's 102.5°F for 3–24 months.
- **Judge errors, in both directions:** it scored Q11 as Incomplete rather than contradicted, and it flagged "My sources don't cover…" and "consult your pediatrician" as claims (Q03, Q10, Q20).
- **One run is one sample:** reruns move about 1–2 questions.
