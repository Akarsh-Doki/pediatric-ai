"""
Tests for prompt building — verifies the RAG prompt is correctly assembled
from patient info, retrieved chunks, and conversation history.
"""
import pytest
from backend.services.generation import build_prompt, assess_urgency


class TestBuildPrompt:
    """Test that the prompt is assembled correctly."""

    def test_includes_system_prompt(self, mock_patient_info):
        messages = build_prompt("test question", [], mock_patient_info)
        assert messages[0]["role"] == "system"
        assert "PediatricAI" in messages[0]["content"]

    def test_includes_patient_info(self, mock_patient_info):
        messages = build_prompt("test", [], mock_patient_info)
        system_content = messages[0]["content"]
        assert "Test Child" in system_content
        assert "Age 5" in system_content
        assert "male" in system_content
        assert "asthma" in system_content

    def test_includes_chunks_when_provided(self, mock_patient_info, mock_chunks_high):
        messages = build_prompt("fever question", mock_chunks_high, mock_patient_info)
        system_content = messages[0]["content"]
        assert "Fever Guide" in system_content
        assert "Source 1" in system_content

    def test_no_chunks_message(self, mock_patient_info):
        messages = build_prompt("random question", [], mock_patient_info)
        system_content = messages[0]["content"]
        assert "No relevant medical context found" in system_content

    def test_user_message_is_last(self, mock_patient_info):
        messages = build_prompt("my question here", [], mock_patient_info)
        assert messages[-1]["role"] == "user"
        assert messages[-1]["content"] == "my question here"

    def test_conversation_history_included(self, mock_patient_info):
        history = [
            {"role": "user", "content": "my baby has a fever"},
            {"role": "assistant", "content": "I understand your concern about the fever."},
        ]
        messages = build_prompt("how much tylenol?", [], mock_patient_info, history)
        # System + 2 history messages + user message = 4
        assert len(messages) == 4
        assert messages[1]["content"] == "my baby has a fever"
        assert messages[2]["content"] == "I understand your concern about the fever."

    def test_history_limited_to_6(self, mock_patient_info):
        """Only last 6 history messages to avoid context overflow."""
        history = [{"role": "user", "content": f"message {i}"} for i in range(10)]
        messages = build_prompt("current question", [], mock_patient_info, history)
        # System + 6 history + user = 8
        assert len(messages) == 8


class TestAssessUrgency:
    """Test post-generation urgency classification."""

    def test_severe_with_911(self):
        assert assess_urgency("Call 911 right now and start CPR", []) == "severe"

    def test_severe_with_emergency(self):
        assert assess_urgency("Go to the emergency room immediately", []) == "severe"

    def test_moderate_with_doctor(self):
        assert assess_urgency("I recommend you see your pediatrician today", []) == "moderate"

    def test_mild_reassurance(self):
        assert assess_urgency("This is very common and usually resolves on its own", []) == "mild"

    def test_none_neutral(self):
        assert assess_urgency("Here are some things you can try at home", []) == "none"