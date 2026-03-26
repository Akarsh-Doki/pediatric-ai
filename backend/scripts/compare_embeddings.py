"""
Compare embedding models for medical retrieval quality.
Run: python -m backend.scripts.compare_embeddings
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sentence_transformers import SentenceTransformer
from backend.models.database import SessionLocal
from sqlalchemy import text

MODELS_TO_TEST = [
    ("all-MiniLM-L6-v2", 384),
    # ("pritamdeka/PubMedBERT-mnli-snli-scinli-scitail-mednli-stsb", 768),
    # Uncomment above after first run — it's a larger download
]

TEST_QUERIES = [
    ("My child has a 102 fever", "fever"),
    ("rash on hands and feet toddler", "hand foot mouth"),
    ("is this ear infection", "otitis media"),
    ("when should baby get vaccinated", "immunization schedule"),
    ("child choking not breathing", "choking"),
    ("how much tylenol for 3 year old", "acetaminophen"),
    ("my baby has eczema flare up", "eczema"),
    ("toddler coughing barking sound", "croup"),
]

def test_model(model_name: str, dim: int):
    print(f"\n{'='*60}")
    print(f"Testing: {model_name} ({dim}d)")
    print(f"{'='*60}")

    model = SentenceTransformer(model_name)
    db = SessionLocal()

    total_queries = len(TEST_QUERIES)
    hits = 0
    total_latency = 0

    for query_text, expected_topic in TEST_QUERIES:
        start = time.time()
        embedding = model.encode(query_text, normalize_embeddings=True).tolist()
        latency_ms = int((time.time() - start) * 1000)
        total_latency += latency_ms

        # Note: this only works if chunks were embedded with the SAME model
        # For comparison, we check if the query embedding produces reasonable similarity
        results = db.execute(text("""
            SELECT d.title, 1 - (c.embedding <=> :emb::vector) AS sim
            FROM chunks c JOIN guideline_docs d ON c.doc_id = d.id
            ORDER BY c.embedding <=> :emb::vector LIMIT 5
        """), {"emb": str(embedding)}).fetchall()

        top_sim = float(results[0].sim) if results else 0
        top_title = results[0].title if results else "none"
        hit = top_sim >= 0.5
        if hit:
            hits += 1

        status = "HIT" if hit else "MISS"
        print(f"  [{status}] \"{query_text}\" → {top_sim:.3f} | {top_title[:50]}")
    
    db.close()
    hit_rate = hits / total_queries * 100
    avg_latency = total_latency / total_queries
    print(f"\nResults: {hits}/{total_queries} hits ({hit_rate:.0f}%), avg latency {avg_latency:.0f}ms")
    return {"model": model_name, "hit_rate": hit_rate, "avg_latency_ms": avg_latency}


def main():
    results = []
    for model_name, dim in MODELS_TO_TEST:
        results.append(test_model(model_name, dim))

    print(f"\n{'='*60}")
    print("COMPARISON SUMMARY")
    print(f"{'='*60}")
    for r in results:
        print(f"  {r['model']}: {r['hit_rate']:.0f}% hit-rate, {r['avg_latency_ms']:.0f}ms avg")


if __name__ == "__main__":
    main()