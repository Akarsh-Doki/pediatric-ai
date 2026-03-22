# Engineering Decisions

This document records every significant technical decision, the alternatives
considered, and the reasoning. Updated as the project progresses.

## Architecture Decisions

### 1. pgvector over Pinecone/Chroma
**Decision:** Use pgvector extension in PostgreSQL.
**Alternatives:** Pinecone (managed), ChromaDB (embedded), Weaviate.
**Reasoning:** Vectors live alongside relational data (patients, conversations,
metadata). Filtered similarity search (WHERE age_range = 'pediatric') happens
in one query instead of requiring two systems. No vendor lock-in. No extra
infrastructure cost. PostgreSQL is an industry-standard skill on a resume.

### 2. Ollama + LLaMA (dev) / OpenAI GPT-4o-mini (prod)
**Decision:** Use LLaMA 3.2 3B via Ollama for development (fits 8GB RAM), OpenAI for production.
**Alternatives:** OpenAI-only, self-hosted in cloud.
**Reasoning:** $0 cost during development. Full local control. Running LLaMA on
AWS requires GPU instances ($50-200+/month) — OpenAI GPT-4o-mini at demo scale
costs pennies. The LLM call is abstracted behind a provider interface, making
the swap transparent.

### 3. SentenceTransformers over OpenAI Embeddings
**Decision:** Use local SentenceTransformers models from Hugging Face.
**Alternatives:** OpenAI text-embedding-3-small, Cohere embed.
**Reasoning:** Free, fast, no API calls during ingestion of 100+ documents.
Medical-domain models available (PubMedBERT).

### 4. Edge TTS over paid TTS
**Decision:** Microsoft Edge TTS (free).
**Alternatives:** ElevenLabs ($5+/mo), Google Cloud TTS (pay per character).
**Reasoning:** Free, natural-sounding British voices, sufficient quality for
portfolio demo. Graceful fallback to text-only if TTS fails.

### 5. React over Streamlit
**Decision:** React 18 + Vite + Tailwind CSS.
**Alternatives:** Streamlit, Gradio.
**Reasoning:** Industry-standard frontend. Enables custom face animations
impossible in Streamlit. Adds React, Vite, Tailwind to resume.

### 6. Chunk size tuning
**Decision:** (To be filled after eval tuning)
**Before:** 1000-token chunks → X% hit-rate
**After:** 600-token chunks → Y% hit-rate

### 7. Embedding model selection
**Decision:** (To be filled after eval comparison)
**all-MiniLM-L6-v2:** X% hit-rate, Yms latency, 384 dimensions
**PubMedBERT:** X% hit-rate, Yms latency, 768 dimensions

### 8. Strict refusal policy
**Decision:** Refuse when retrieval similarity < 0.65 or fewer than 2 chunks
above threshold.
**Reasoning:** A medical system that guesses is more dangerous than one that
says "I don't know." This is the most important safety feature.

### 9. No DVC (Data Version Control)
**Decision:** Track corpus manifest in Git directly.
**Reasoning:** The corpus is ~100-200 static PDFs ingested once. DVC is
designed for teams iterating on large ML datasets over months. A JSON manifest
is sufficient.

### 10. Emergency-first response pattern
**Decision:** For life-threatening inputs, the system front-loads "Call 911"
before any instructions.
**Reasoning:** A parent reading CPR steps is losing seconds. The 911 prompt
is hardcoded into the emergency template, not left to the LLM.