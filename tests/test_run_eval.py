"""Tests for the pure scoring logic in eval/run_eval.py (verdict rules, recall@5,
confidence intervals, judge-vs-human agreement) and the integrity of eval/questions.csv.
No DB, network, or LLM needed."""
import sys
import types
from collections import Counter

import eval.run_eval as run_eval
from eval.run_eval import (
    _normalize_label, cohens_kappa, evidence_pool, final_verdict, load_questions, recall_at_k,
    wilson_interval,
)

SUPPORTED = {"claim": "x", "status": "supported"}
NOT_FOUND = {"claim": "y", "status": "not_found"}
CONTRADICTED = {"claim": "z", "status": "contradicted"}


class TestFinalVerdict:
    def test_correct_needs_match_and_all_supported(self):
        assert final_verdict([SUPPORTED], False, True, in_scope=True) == "Correct"

    def test_any_unsupported_claim_wins(self):
        assert final_verdict([SUPPORTED, NOT_FOUND], False, True, in_scope=True) == "Unsupported"
        assert final_verdict([CONTRADICTED], False, True, in_scope=True) == "Unsupported"

    def test_decline_that_still_makes_unsupported_claim_is_unsupported(self):
        assert final_verdict([NOT_FOUND], True, None, in_scope=False) == "Unsupported"

    def test_clean_decline(self):
        assert final_verdict([], True, None, in_scope=False) == "Declined"
        assert final_verdict([], True, False, in_scope=True) == "Declined"

    def test_supported_but_misses_reference_is_incomplete(self):
        assert final_verdict([SUPPORTED], False, False, in_scope=True) == "Incomplete"

    def test_bare_emergency_referrals_are_exempt(self):
        for text in ["Call 911 right now.", "Call Poison Control at 1-800-222-1222 right now.",
                     "call poison control immediately", "Dial 911."]:
            claim = {"claim": text, "status": "not_found"}
            assert final_verdict([claim, SUPPORTED], False, True, in_scope=True) == "Correct", text

    def test_emergency_referral_with_medical_criterion_still_counts(self):
        claim = {"claim": "Call 911 if the seizure lasts more than 5 minutes.", "status": "not_found"}
        assert final_verdict([claim], False, True, in_scope=True) == "Unsupported"

    def test_out_of_scope_cannot_be_correct(self):
        assert final_verdict([SUPPORTED], False, True, in_scope=False) == "Incomplete"


class TestRecallAt5:
    def test_hit_inside_top5(self):
        assert recall_at_k(["a", "b", "c", "d", "gold"], ["gold"]) == 1

    def test_hit_at_rank_6_does_not_count(self):
        assert recall_at_k(["a", "b", "c", "d", "e", "gold"], ["gold"]) == 0

    def test_any_of_several_gold_chunks(self):
        assert recall_at_k(["x", "g2"], ["g1", "g2"]) == 1

    def test_nothing_retrieved(self):
        assert recall_at_k([], ["gold"]) == 0


class TestStats:
    def test_wilson_contains_point_estimate(self):
        lo, hi = wilson_interval(30, 60)
        assert lo < 0.5 < hi

    def test_wilson_zero_successes_has_nonzero_upper_bound(self):
        lo, hi = wilson_interval(0, 20)
        assert lo == 0.0 and hi > 0.1

    def test_kappa_perfect_and_chance(self):
        assert cohens_kappa(["C", "U", "D"], ["C", "U", "D"]) == 1.0
        assert abs(cohens_kappa(["C", "C", "U", "U"], ["C", "U", "C", "U"])) < 1e-9

    def test_label_normalization(self):
        assert _normalize_label("correct") == "Correct"
        assert _normalize_label(" U ") == "Unsupported"
        assert _normalize_label("d") == "Declined"
        assert _normalize_label("") is None
        assert _normalize_label("maybe") is None


class _FakeVector(list):
    def tolist(self):
        return list(self)


class _FakeDB:
    """Returns neighbours based on the sentence index encoded in the fake vector."""
    def execute(self, sql, params):
        i = int(params["e"].strip("[]").split(",")[0])
        return [types.SimpleNamespace(id=f"u-n{i}"), types.SimpleNamespace(id=f"u-s{i}")]


class TestEvidencePool:
    def _run(self, monkeypatch, answers, gold, retrieved, max_chunks):
        model = types.SimpleNamespace(
            encode=lambda sents, normalize_embeddings: [_FakeVector([i]) for i in range(len(sents))])
        stub = types.ModuleType("backend.utils.embeddings")
        stub.get_embedding_model = lambda: model
        monkeypatch.setitem(sys.modules, "backend.utils.embeddings", stub)
        ids = [f"n{i}" for i in range(20)] + [f"s{i}" for i in range(20)]
        corpus = {"by_uuid": {f"u-{x}": x for x in ids}}
        return evidence_pool(_FakeDB(), answers, gold, retrieved, corpus, max_chunks)

    def test_priority_order_and_cap(self, monkeypatch):
        answers = ["First sentence of the off answer is here. Second off sentence is right here.",
                   "Only sentence of the on answer is long enough."]
        retrieved = [f"r{i}" for i in range(7)]
        pool = self._run(monkeypatch, answers, ["g1"], retrieved, max_chunks=12)
        # gold, top-5 retrieved, nearest per sentence (3 sentences), then retrieved 6-7, then 2nd-nearest
        assert pool == ["g1", "r0", "r1", "r2", "r3", "r4", "n0", "n1", "n2", "r5", "r6", "s0"]

    def test_sentences_from_both_answers_alternate(self, monkeypatch):
        answers = ["Off answer sentence number one. Off answer sentence number two.",
                   "On answer sentence number one. On answer sentence number two."]
        pool = self._run(monkeypatch, answers, [], [], max_chunks=2)
        # With room for only 2, one neighbour from each answer's first sentence gets in.
        assert pool == ["n0", "n1"]

    def test_no_duplicates(self, monkeypatch):
        pool = self._run(monkeypatch, ["Short."], ["g1", "g1"], ["g1", "r1"], max_chunks=10)
        assert pool == ["g1", "r1"]


class TestUsage:
    def test_cost_counts_cached_tokens_at_cached_price(self, monkeypatch, capsys):
        monkeypatch.setattr(run_eval, "USAGE", {})
        run_eval._record_usage("gpt-4o", {"usage": {
            "prompt_tokens": 1_000_000, "completion_tokens": 100_000,
            "prompt_tokens_details": {"cached_tokens": 400_000}}})
        assert run_eval.USAGE["gpt-4o"] == Counter(calls=1, input=1_000_000, cached=400_000, output=100_000)
        run_eval.print_usage()
        # 600k * $2.50 + 400k * $1.25 + 100k * $10 per 1M = 1.50 + 0.50 + 1.00
        assert "~$3.00" in capsys.readouterr().out

    def test_ollama_response_without_usage_is_ignored(self, monkeypatch):
        monkeypatch.setattr(run_eval, "USAGE", {})
        run_eval._record_usage("llama3.2:3b", {"message": {"content": "hi"}})
        assert run_eval.USAGE == {}


class TestQuestionSet:
    def test_counts_and_labels(self):
        qs = load_questions()
        assert len(qs) == 80
        assert len({q["id"] for q in qs}) == 80
        in_scope = [q for q in qs if q["in_scope"]]
        assert len(in_scope) == 60
        for q in in_scope:
            assert q["gold_ids"] and q["reference_answer"] and q["evidence_quote"]
            assert q["gold_ids"][0].startswith(q["source_document"] + "#")
        for q in qs:
            if not q["in_scope"]:
                assert not q["gold_ids"] and not q["reference_answer"]

    def test_covers_all_12_documents(self):
        docs = {q["source_document"] for q in load_questions() if q["in_scope"]}
        assert len(docs) == 12
