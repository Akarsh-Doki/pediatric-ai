import logging
import uuid
import json
from pathlib import Path
from datetime import datetime

import fitz  # PyMuPDF parses pdfs
from sqlalchemy.orm import Session

from backend.models.database import GuidelineDoc, Chunk
from backend.utils.chunking import chunk_text
from backend.utils.embeddings import embed_batch

logger = logging.getLogger("pediatricai")

MANIFEST_PATH = "data/corpus_manifest.json" # Path to a JSON file that tracks what's been ingested


def extract_text_from_pdf(file_path: str) -> list[dict]: # This opens the pdf file and loads it into memory
    doc = fitz.open(file_path)
    pages = [] # This code iterates through every page and extracts all the text content in reading order
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text = page.get_text("text")
        if text.strip():
            pages.append({"page_num": page_num + 1, "text": text.strip()})
    doc.close()
    logger.info(f"Extracted {len(pages)} pages from {file_path}") # logs the number of pages of text that there was
    return pages


def detect_section_type(text: str) -> str: # Classifies what kind of medical content a chunk contains
    text_lower = text.lower()
    if any(w in text_lower for w in ["symptom", "signs", "presents with", "characterized by"]):
        return "symptoms"
    if any(w in text_lower for w in ["treatment", "therapy", "manage", "administer", "prescribe"]):
        return "treatment"
    if any(w in text_lower for w in ["dosage", "dose", "mg/kg", "milligram", "concentration"]):
        return "dosage"
    if any(w in text_lower for w in ["contraindic", "do not use", "avoid", "warning", "precaution"]):
        return "contraindications"
    if any(w in text_lower for w in ["emergency", "911", "cpr", "choking", "unconscious"]):
        return "emergency"
    if any(w in text_lower for w in ["prevent", "vaccine", "immuniz", "schedule"]):
        return "prevention"
    return "general" # Falls through to "general" if no keywords match


def detect_condition_category(text: str) -> str: # A second classifier for medical category
    text_lower = text.lower()
    categories = {
        "respiratory": ["cough", "breathing", "wheez", "asthma", "bronch", "pneumonia", "croup", "rsv"],
        "dermatology": ["rash", "skin", "eczema", "hives", "itch", "ringworm", "lice"],
        "gastrointestinal": ["vomit", "diarrhea", "stomach", "nausea", "constipat", "abdomin"],
        "infectious": ["fever", "infect", "virus", "bacteria", "contagious", "strep"],
        "neurological": ["headache", "seizure", "concussion", "migraine"],
        "musculoskeletal": ["fracture", "sprain", "pain", "swell", "injury"],
        "ear_nose_throat": ["ear", "otitis", "throat", "tonsil", "sinus"],
        "dental": ["tooth", "teeth", "dental", "gum", "cavity"],
        "eye": ["eye", "vision", "pink eye", "conjunctiv"],
        "developmental": ["milestone", "development", "speech", "walking", "growth"],
        "nutrition": ["feed", "nutrition", "diet", "breastfeed", "formula", "vitamin"],
        "medication": ["medication", "drug", "tylenol", "ibuprofen", "antibiotic", "dosage"],
        "immunization": ["vaccine", "immuniz", "shot", "booster"],
        "emergency": ["emergency", "cpr", "choking", "poison", "911", "unconscious"],
        "mental_health": ["anxiety", "depress", "adhd", "autism", "behavior"],
    }
    for category, keywords in categories.items(): # Iterates through categories in dict order
        if any(kw in text_lower for kw in keywords):
            return category
    return "general"


def update_corpus_manifest(title: str, source: str, file_path: str, chunks_created: int): # Reads the existing manifest JSON, or creates a new one if it doesn't exist or is corrupted
    """Update the Git-tracked corpus manifest JSON."""
    try:
        with open(MANIFEST_PATH) as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {"description": "PediatricAI corpus manifest", "documents": []}

    manifest["last_updated"] = datetime.utcnow().isoformat() # Appends a new entry and writes the JSON back
    manifest["documents"].append({
        "title": title,
        "source": source,
        "file_path": file_path,
        "chunks_created": chunks_created,
        "ingested_at": datetime.utcnow().isoformat(),
    })

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)


def ingest_document(db: Session, doc_id: uuid.UUID) -> int: # Validates the document exists in the database and the PDF file exists on disk
    doc = db.query(GuidelineDoc).filter(GuidelineDoc.id == doc_id).first()
    if not doc:
        raise ValueError(f"Document {doc_id} not found")
    if not doc.file_path or not Path(doc.file_path).exists():
        raise FileNotFoundError(f"File not found: {doc.file_path}")

    logger.info(f"Starting ingestion of: {doc.title}")

    pages = extract_text_from_pdf(doc.file_path) # Turns the PDF into a list of {page_num, text} dicts.

    all_chunks = [] # For each page, splits the text into ~600-token pieces
    for page_data in pages:
        page_chunks = chunk_text(page_data["text"])
        for chunk_str in page_chunks:
            all_chunks.append({"text": chunk_str, "page_num": page_data["page_num"]})

    if not all_chunks: # scanned PDFs without OCR produce no text
        logger.warning(f"No text extracted from {doc.title}")
        return 0

    texts = [c["text"] for c in all_chunks] # Extracts just the text strings and passes them to the embedding model in one batch. embed_batch calls model.encode(texts, normalize_embeddings=True) which processes all chunks at once through the neural network
    embeddings = embed_batch(texts)

    chunk_records = [] # zip(all_chunks, embeddings) pairs each chunk with its embedding
    for i, (chunk_data, embedding) in enumerate(zip(all_chunks, embeddings)):
        chunk_records.append(Chunk(
            doc_id=doc_id,
            chunk_text=chunk_data["text"],
            embedding=embedding,
            section_type=detect_section_type(chunk_data["text"]),
            age_range="pediatric",
            condition_category=detect_condition_category(chunk_data["text"]),
            page_num=chunk_data["page_num"],
            chunk_index=i,
        ))

    db.bulk_save_objects(chunk_records)
    db.commit()
    update_corpus_manifest(doc.title, doc.source, doc.file_path, len(chunk_records)) # Updates the manifest file, logs, and returns the chunk count.
    logger.info(f"Ingested {len(chunk_records)} chunks from '{doc.title}'")
    return len(chunk_records)