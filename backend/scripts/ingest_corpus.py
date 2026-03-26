"""
Bulk ingestion script. Run from project root:
    python -m backend.scripts.ingest_corpus
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sqlalchemy.orm import Session
from backend.models.database import SessionLocal, GuidelineDoc
from backend.services.ingestion import ingest_document

GUIDELINES_DIR = "data/guidelines"


def get_source_from_filename(filename: str) -> str:
    fl = filename.lower()
    # CDC sources
    if "cdc" in fl or "vaccine" in fl or "immuniz" in fl or "milestone" in fl:
        return "CDC"
    # WHO sources
    if "who" in fl or "imci" in fl:
        return "WHO"
    # AAP / HealthyChildren.org sources
    if "aap" in fl or "healthychildren" in fl:
        return "AAP"
    # MedlinePlus / NIH sources
    if "medlineplus" in fl or "medline" in fl or "nlm" in fl:
        return "MedlinePlus/NIH"
    # FDA DailyMed drug labels
    if "dailymed" in fl or "tylenol" in fl or "motrin" in fl or "amoxicillin" in fl \
       or "zyrtec" in fl or "benadryl" in fl or "acetaminophen" in fl or "ibuprofen" in fl:
        return "FDA/DailyMed"
    # Compiled reference PDFs (cover multiple MedlinePlus/DailyMed topics)
    if "pediatric-medical-reference" in fl or "pediatric_medical_reference" in fl:
        return "MedlinePlus/NIH (Compiled Guide)"
    if "pediatric-medications-reference" in fl or "pediatric_medications_reference" in fl:
        return "FDA/DailyMed (Compiled Guide)"
    # Generated multi-source compiled PDFs (check BEFORE generic keyword matches)
    if "pediatric-health-guide" in fl or "children-health-guide" in fl \
       or "pediatric_health_guide" in fl or "children_health_guide" in fl:
        return "AAP/CDC (Compiled Guide)"
    if "emergency-first-aid" in fl or "emergency_first_aid" in fl:
        return "Red Cross/AAP (Compiled Guide)"
    if "common-childhood-conditions" in fl or "common_childhood_conditions" in fl:
        return "MedlinePlus/AAP (Compiled Guide)"
    # Red Cross / first aid (generic)
    if "red cross" in fl or "redcross" in fl or "first aid" in fl or "first-aid" in fl:
        return "American Red Cross"
    # Children's hospital fever guides
    if "fever" in fl:
        return "Pediatric Hospital Reference"
    # Common condition keywords (fallback)
    if "cough" in fl or "rash" in fl or "teething" in fl \
       or "bronchiolitis" in fl or "croup" in fl or "rsv" in fl or "asthma" in fl \
       or "eczema" in fl or "chickenpox" in fl or "lice" in fl or "ringworm" in fl \
       or "flu" in fl or "strep" in fl or "pinkeye" in fl or "conjunctivitis" in fl \
       or "gastroenteritis" in fl or "cold" in fl or "uti" in fl or "urinary" in fl \
       or "nosebleed" in fl or "cradle" in fl or "ear-infection" in fl:
        return "MedlinePlus/NIH"
    if "poison" in fl:
        return "Poison Control/AAP"
    if "cpr" in fl or "choking" in fl:
        return "American Red Cross"
    if "sleep" in fl or "sids" in fl or "breastfeed" in fl or "newborn" in fl \
       or "nutrition" in fl or "development" in fl:
        return "AAP"
    return "Medical Reference"


def main():
    db: Session = SessionLocal()

    pdf_files = []
    for root, dirs, files in os.walk(GUIDELINES_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, f))

    if not pdf_files:
        print(f"No PDF files found in {GUIDELINES_DIR}/")
        print("Please download medical PDFs first (see guide Phase 4.1)")
        return

    print(f"Found {len(pdf_files)} PDF files to ingest")
    print("=" * 60)

    total_chunks = 0
    for i, pdf_path in enumerate(pdf_files, 1):
        filename = os.path.basename(pdf_path)
        title = filename.replace(".pdf", "").replace("_", " ").replace("-", " ").title()
        source = get_source_from_filename(filename)

        print(f"\n[{i}/{len(pdf_files)}] {title}")
        print(f"  Source: {source}")

        existing = db.query(GuidelineDoc).filter(GuidelineDoc.file_path == pdf_path).first()
        if existing:
            print(f"  SKIPPED (already ingested)")
            continue

        doc = GuidelineDoc(title=title, source=source, file_path=pdf_path)
        db.add(doc)
        db.commit()
        db.refresh(doc)

        try:
            chunks = ingest_document(db, doc.id)
            total_chunks += chunks
            print(f"  OK: {chunks} chunks created")
        except Exception as e:
            print(f"  ERROR: {e}")
            db.rollback()

    print(f"\n{'=' * 60}\nIngestion complete. Total chunks: {total_chunks}")
    db.close()


if __name__ == "__main__":
    main()