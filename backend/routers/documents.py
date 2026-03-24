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
router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(
    file: UploadFile = File(...),
    title: str = None,
    source: str = "user_upload",
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    os.makedirs(settings.upload_dir, exist_ok=True)

    file_id = str(uuid.uuid4())
    file_path = os.path.join(settings.upload_dir, f"{file_id}.pdf")

    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    with open(file_path, "wb") as f:
        f.write(content)

    doc = GuidelineDoc(title=title or file.filename, source=source, file_path=file_path)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    logger.info(f"Uploaded document: {doc.title} ({doc.id})")
    return DocumentUploadResponse(document_id=doc.id, title=doc.title)


@router.post("/{doc_id}/ingest", response_model=IngestResponse)
def ingest_doc(doc_id: uuid.UUID, db: Session = Depends(get_db)):
    doc = db.query(GuidelineDoc).filter(GuidelineDoc.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        chunks_created = ingest_document(db, doc_id)
        return IngestResponse(message="Ingestion complete", document_id=doc_id, chunks_created=chunks_created)
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("")
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(GuidelineDoc).order_by(GuidelineDoc.created_at.desc()).all()
    result = []
    for d in docs:
        chunk_count = db.query(Chunk).filter(Chunk.doc_id == d.id).count()
        result.append({
            "id": str(d.id), "title": d.title, "source": d.source,
            "category": d.category, "chunk_count": chunk_count,
            "created_at": d.created_at.isoformat(),
        })
    return result