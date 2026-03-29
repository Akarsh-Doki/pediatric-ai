import logging
from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.utils.embeddings import embed_text
from backend.config import get_settings

logger = logging.getLogger("pediatricai")
settings = get_settings()


def search_chunks(
    db: Session,
    query: str,
    top_k: int = None,
    age_range: str = None,
    condition_category: str = None,
) -> list[dict]:
    if top_k is None:
        top_k = settings.retrieval_top_k

    query_embedding = embed_text(query)

    filters = []
    params = {
        "embedding": str(query_embedding),
        "top_k": top_k,
        "threshold": settings.similarity_threshold,
    }

    if age_range:
        filters.append("c.age_range = :age_range")
        params["age_range"] = age_range
    if condition_category:
        filters.append("c.condition_category = :condition_category")
        params["condition_category"] = condition_category

    where_clause = "WHERE " + " AND ".join(filters) if filters else ""

    sql = text(f"""
        SELECT c.id, c.chunk_text, c.page_num, c.section_type,
               c.condition_category, c.doc_id,
               d.title AS doc_title, d.source AS doc_source,
               1 - (c.embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM chunks c
        JOIN guideline_docs d ON c.doc_id = d.id
        {where_clause}
        ORDER BY c.embedding <=> CAST(:embedding AS vector)
        LIMIT :top_k
    """)

    results = db.execute(sql, params).fetchall()

    chunks = []
    for row in results:
        sim = float(row.similarity)
        if sim >= settings.similarity_threshold:
            chunks.append({
                "id": str(row.id),
                "chunk_text": row.chunk_text,
                "page_num": row.page_num,
                "section_type": row.section_type,
                "condition_category": row.condition_category,
                "doc_id": str(row.doc_id),
                "doc_title": row.doc_title,
                "doc_source": row.doc_source,
                "similarity": sim,
            })

    logger.info(f"Retrieved {len(chunks)} chunks above threshold")
    return chunks