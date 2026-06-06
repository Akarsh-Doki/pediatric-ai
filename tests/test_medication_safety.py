"""Tests for the deterministic medication-safety layer (TIER 1, feature #1 — flagship).

The whole point of this layer is that it CANNOT silently miss a pasted allergy the way
an LLM can, so these tests pin the hard guarantees: an allergy conflict blocks, a
hidden duplicate ingredient inside a combo product is caught, a known interaction warns,
aspirin is contraindicated in a child, a clean drug passes, and an unknown drug degrades
to an informational "couldn't verify" note rather than a false all-clear.

Self-contained by design (no conftest fixtures) so it runs under repo pytest AND under
the offline stdlib runner used during the build.
"""
from backend.services.medication_safety import (
    check_medication,
    normalize_to_ingredients,
    scan_text_for_medications,
)


def _types(result):
    return {w["type"] for w in result.warnings}


class TestAllergyConflict:
    def test_documented_allergy_blocks(self):
        # Penicillin allergy on file, candidate is amoxicillin (a penicillin) -> hard block.
        patient = {"age": 7, "known_conditions": ["penicillin allergy"], "medications": []}
        r = check_medication(patient, "amoxicillin")
        assert r.blocked is True
        assert r.safe is False
        assert r.max_severity == "block"
        assert "allergy" in _types(r)
        w = next(w for w in r.warnings if w["type"] == "allergy")
        assert w["ingredient"] == "amoxicillin"
        assert w["related"] == "penicillin"

    def test_cross_reactivity_warns_but_does_not_block(self):
        # Penicillin allergy + a cephalosporin (cephalexin): real cross-reactivity, but a
        # caution rather than an absolute block. Must NOT be treated as a clean pass.
        patient = {"age": 7, "known_conditions": ["penicillin allergy"], "medications": []}
        r = check_medication(patient, "cephalexin")
        assert r.blocked is False
        assert r.max_severity == "caution"
        assert "cross_reactivity" in _types(r)


class TestDuplicateIngredient:
    def test_hidden_duplicate_in_combo_product_caught(self):
        # Child already on plain Tylenol; caregiver asks about Children's Tylenol Cold,
        # which HIDES acetaminophen among other ingredients. Deterministic code unpacks
        # the combo and flags the duplicate -> overdose risk.
        patient = {"age": 5, "known_conditions": [], "medications": [{"name": "tylenol"}]}
        r = check_medication(patient, "children's tylenol cold")
        assert "duplicate_ingredient" in _types(r)
        assert r.safe is False
        assert r.max_severity == "high"
        dup = next(w for w in r.warnings if w["type"] == "duplicate_ingredient")
        assert dup["ingredient"] == "acetaminophen"


class TestInteraction:
    def test_known_interaction_flagged(self):
        # Two NSAIDs together (naproxen on file + ibuprofen candidate) -> interaction.
        patient = {"age": 10, "known_conditions": [], "medications": [{"name": "naproxen"}]}
        r = check_medication(patient, "ibuprofen")
        assert "interaction" in _types(r)
        inter = next(w for w in r.warnings if w["type"] == "interaction")
        assert inter["related"] == "naproxen"


class TestPediatricContraindication:
    def test_aspirin_blocked_in_child(self):
        # Aspirin in a child -> Reye's-syndrome contraindication, hard block,
        # independent of allergies or current meds.
        patient = {"age": 7, "known_conditions": [], "medications": []}
        r = check_medication(patient, "aspirin")
        assert r.blocked is True
        assert r.max_severity == "block"
        assert "pediatric_contraindication" in _types(r)


class TestSafeAndUnknown:
    def test_clean_drug_passes(self):
        patient = {"age": 5, "known_conditions": [], "medications": []}
        r = check_medication(patient, "acetaminophen")
        assert r.blocked is False
        assert r.safe is True
        assert r.warnings == []
        assert r.max_severity == "none"

    def test_unknown_drug_is_info_not_false_allclear(self):
        # An unrecognized name must surface an explicit "couldn't verify" note, never a
        # silent pass that looks identical to a verified-safe result.
        patient = {"age": 5, "known_conditions": [], "medications": []}
        r = check_medication(patient, "zzzpotion")
        assert r.ingredients == []
        assert r.max_severity == "info"
        assert "unknown_drug" in _types(r)


class TestNormalizationAndScan:
    def test_combo_product_unpacks_to_all_ingredients(self):
        ings = normalize_to_ingredients("children's tylenol cold")
        assert "acetaminophen" in ings
        assert len(ings) > 1  # combo, not a single ingredient

    def test_brand_resolves_to_generic(self):
        assert normalize_to_ingredients("motrin") == ["ibuprofen"]

    def test_unknown_name_resolves_empty(self):
        assert normalize_to_ingredients("zzzpotion") == []

    def test_scan_free_text_finds_mentions(self):
        hits = scan_text_for_medications("I gave her some Tylenol and a bit of motrin earlier")
        assert "tylenol" in hits
        assert "motrin" in hits
