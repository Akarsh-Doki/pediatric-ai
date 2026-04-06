import pytest
from backend.utils.symptoms import extract_symptoms


class TestSymptomDetection:
    """Test that natural language parent descriptions extract correct symptoms."""

    def test_fever_detection(self):
        result = extract_symptoms("My child has a fever of 102")
        assert "fever" in result["symptoms"]

    def test_colloquial_fever(self):
        result = extract_symptoms("She's burning up")
        assert "fever" in result["symptoms"]

    def test_cough_detection(self):
        result = extract_symptoms("He has a terrible cough")
        assert "cough" in result["symptoms"]

    def test_barking_cough(self):
        result = extract_symptoms("It's a barking cough, worse at night")
        assert "cough" in result["symptoms"]

    def test_vomiting_colloquial(self):
        result = extract_symptoms("She keeps throwing up")
        assert "vomiting" in result["symptoms"]

    def test_multiple_symptoms(self):
        result = extract_symptoms("My child has a fever, is coughing, and won't eat")
        assert "fever" in result["symptoms"]
        assert "cough" in result["symptoms"]
        assert "loss_of_appetite" in result["symptoms"]

    def test_no_symptoms(self):
        result = extract_symptoms("When is the next well-child visit?")
        assert len(result["symptoms"]) == 0

    def test_breathing_difficulty(self):
        result = extract_symptoms("She can't breathe properly")
        assert "breathing_difficulty" in result["symptoms"]

    def test_ear_pulling(self):
        result = extract_symptoms("He keeps pulling at his ear")
        assert "earache" in result["symptoms"]


class TestSeverityEstimation:
    """Test that severity keywords are correctly classified."""

    def test_severe_choking(self):
        result = extract_symptoms("My baby is choking and turning blue")
        assert result["severity_estimate"] == "severe"

    def test_severe_unconscious(self):
        result = extract_symptoms("My child is unconscious and not responding")
        assert result["severity_estimate"] == "severe"

    def test_moderate_high_fever(self):
        result = extract_symptoms("She has a high fever of 104")
        assert result["severity_estimate"] == "moderate"

    def test_mild_regular_symptom(self):
        result = extract_symptoms("He has a runny nose")
        assert result["severity_estimate"] == "mild"

    def test_unknown_no_symptoms(self):
        result = extract_symptoms("How are you today?")
        assert result["severity_estimate"] == "unknown"