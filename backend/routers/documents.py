import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from backend.models.database import get_db, GuidelineDoc, Chunk
from backend.models.schemas import DocumentUploadResponse, IngestResponse
from backend.services.ingestion import ingest_document
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()
router = APIRouter(prefix="/documents", tags=["documents"]) # makes it so all the endpoints start with /documents


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document( # async def because file reading is I/O-bound
    file: UploadFile = File(...),
    title: str = None,
    source: str = "user_upload",
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"): # If not pdf, raises 400 bad request
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    os.makedirs(settings.upload_dir, exist_ok=True) # makes the upload directory and doesn't if its already made

    file_id = str(uuid.uuid4()) # Generates a random filename like 3a7b2c4d-...-8f9e.pdf
    file_path = os.path.join(settings.upload_dir, f"{file_id}.pdf")

    content = await file.read() # Reads the entire file into meory, and it prevents someone from uploading a file above 50 mb
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    with open(file_path, "wb") as f: # Writes the bytes to disk using write binary mode
        f.write(content)

    doc = GuidelineDoc(title=title or file.filename, source=source, file_path=file_path) # Creates a database record for this document
    db.add(doc)
    db.commit()
    db.refresh(doc)
    logger.info(f"Uploaded document: {doc.title} ({doc.id})")
    return DocumentUploadResponse(document_id=doc.id, title=doc.title)


@router.post("/{doc_id}/ingest", response_model=IngestResponse)
def ingest_doc(doc_id: uuid.UUID, db: Session = Depends(get_db)): # ingesting is slow, so it is a seperate function than uploading
    doc = db.query(GuidelineDoc).filter(GuidelineDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        chunks_created = ingest_document(db, doc_id) # Calls the ingestion service. If it fails (corrupt PDF, database error), catches the exception, logs it, and returns 500. 
        return IngestResponse(message="Ingestion complete", document_id=doc_id, chunks_created=chunks_created)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(GuidelineDoc).order_by(GuidelineDoc.created_at.desc()).all()
    result = []
    for d in docs: # For each document, counts how many chunks it produced. Shows in the frontend: "Common Childhood Conditions — 24 chunks
        chunk_count = db.query(Chunk).filter(Chunk.doc_id == d.id).count()
        result.append({ # Builds the response manually as dicts
            "id": str(d.id), "title": d.title, "source": d.source,
            "category": d.category, "chunk_count": chunk_count,
            "created_at": d.created_at.isoformat(),
        })
    return result