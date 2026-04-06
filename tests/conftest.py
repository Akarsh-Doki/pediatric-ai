import pytest
from unittest.mock import MagicMock
from backend.config import get_settings


@pytest.fixture
def settings():
    """Return application settings for tests."""
    return get_settings()


@pytest.fixture
def mock_chunks_high():
    """Simulated retrieval results with HIGH similarity (good RAG match)."""
    return [
        {"id": "1", "chunk_text": "Fever in children is common. A temperature of 100.4F or higher is considered a fever.",
         "page_num": 1, "section_type": "symptoms", "condition_category": "infectious",
         "doc_id": "d1", "doc_title": "Fever Guide", "doc_source": "Pediatric Hospital Reference",
         "similarity": 0.78},
        {"id": "2", "chunk_text": "Treatment includes fluids, rest, and acetaminophen for comfort.",
         "page_num": 2, "section_type": "treatment", "condition_category": "infectious",
         "doc_id": "d1", "doc_title": "Fever Guide", "doc_source": "Pediatric Hospital Reference",
         "similarity": 0.71},
        {"id": "3", "chunk_text": "Call your doctor if fever exceeds 104F or lasts more than 3 days.",
         "page_num": 2, "section_type": "dosage", "condition_category": "infectious",
         "doc_id": "d1", "doc_title": "Fever Guide", "doc_source": "Pediatric Hospital Reference",
         "similarity": 0.65},
    ]


@pytest.fixture
def mock_chunks_low():
    """Simulated retrieval results with LOW similarity (borderline match)."""
    return [
        {"id": "4", "chunk_text": "General wellness checkups are recommended annually.",
         "page_num": 1, "section_type": "general", "condition_category": "general",
         "doc_id": "d2", "doc_title": "Well-Child Visits", "doc_source": "AAP",
         "similarity": 0.48},
    ]


@pytest.fixture
def mock_chunks_empty():
    """Empty retrieval results (no relevant chunks found)."""
    return []


@pytest.fixture
def mock_patient_info():
    """Sample patient information for prompt building."""
    return {
        "name": "Test Child",
        "age": 5,
        "sex": "male",
        "weight_kg": 18.0,
        "known_conditions": ["asthma"],
        "medications": [],
    }