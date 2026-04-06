import pytest
from backend.services.clarification import detect_ambiguity


class TestSpecificQueriesPassThrough:
    """Queries with enough medical detail should NOT be flagged as ambiguous."""

    def test_fever_with_temperature(self):
        result = detect_ambiguity("My child has a 102 fever")
        assert result["is_ambiguous"] is False

    def test_named_condition(self):
        result = detect_ambiguity("My toddler has croup")
        assert result["is_ambiguous"] is False

    def test_specific_symptom(self):
        result = detect_ambiguity("My baby has a barking cough and won't eat")
        assert result["is_ambiguous"] is False

    def test_medication_question(self):
        result = detect_ambiguity("Can I give my child Tylenol with antibiotics?")
        assert result["is_ambiguous"] is False

    def test_body_part_with_problem(self):
        result = detect_ambiguity("My daughter's ear hurts and she has a fever")
        assert result["is_ambiguous"] is False

    def test_emergency_question(self):
        result = detect_ambiguity("My child is choking and can't breathe")
        assert result["is_ambiguous"] is False

    def test_vaccine_question(self):
        result = detect_ambiguity("When should my baby get vaccinated?")
        assert result["is_ambiguous"] is False

    def test_er_question(self):
        result = detect_ambiguity("When should I take my child to the ER?")
        assert result["is_ambiguous"] is False


class TestVagueQueriesCaught:
    """Vague queries should be flagged and get follow-up questions."""

    def test_child_is_sick(self):
        result = detect_ambiguity("My child is sick")
        assert result["is_ambiguous"] is True
        assert result["followup_question"] is not None

    def test_something_is_wrong(self):
        result = detect_ambiguity("Something is wrong")
        assert result["is_ambiguous"] is True

    def test_not_feeling_well(self):
        result = detect_ambiguity("not feeling well")
        assert result["is_ambiguous"] is True

    def test_should_i_be_worried(self):
        result = detect_ambiguity("should I be worried")
        assert result["is_ambiguous"] is True

    def test_help(self):
        result = detect_ambiguity("help")
        assert result["is_ambiguous"] is True

    def test_too_short(self):
        result = detect_ambiguity("he sick")
        assert result["is_ambiguous"] is True


class TestGreetingsPassThrough:
    """Greetings should NOT be flagged as ambiguous — they go to the LLM."""

    def test_hi(self):
        result = detect_ambiguity("hi")
        assert result["is_ambiguous"] is False

    def test_hello(self):
        result = detect_ambiguity("hello")
        assert result["is_ambiguous"] is False

    def test_thanks(self):
        result = detect_ambiguity("thanks")
        assert result["is_ambiguous"] is False


class TestContextualFollowups:
    """When a query is vague but has clues, the follow-up should be targeted."""

    def test_vague_with_fever_clue(self):
        result = detect_ambiguity("my kid is sick with fever")
        # "fever" is specific enough to pass through — this is correct behavior
        assert result["is_ambiguous"] is False

    def test_generic_vague_gets_followup(self):
        result = detect_ambiguity("something is wrong")
        assert result["is_ambiguous"] is True
        assert result["followup_question"] is not None
        assert len(result["followup_question"]) > 20