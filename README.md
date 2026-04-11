# PediatricAI

An AI pediatrician with an expressive animated face, calm synthesized voice,
and medically-grounded RAG that triages symptoms and explains conditions in plain English.

> ⚠️ Portfolio project. Not medical advice. See [MEDICAL_DISCLAIMER.md](MEDICAL_DISCLAIMER.md).

![PediatricAI Screenshot](docs/screenshot.png)

## Quick Start

\`\`\`bash
git clone https://github.com/YOUR_USERNAME/pediatric-ai.git
cd pediatric-ai
cp .env.example .env
docker compose up --build
# Open http://localhost:3000
\`\`\`

Requires: Docker Desktop, Ollama with `llama3.2:3b`

## Capabilities

- **Symptom triage** — Retrieves from 100+ medical guidelines (AAP, CDC, WHO) with citations
- **Bridge care** — Always provides actionable steps NOW, never just "see a doctor"
- **Emergency mode** — Detects life-threatening keywords, front-loads 911 + first aid steps
- **Safety-first** — Never gives dosages; refuses on insufficient evidence; every claim cited

## Architecture

\`\`\`
User → React Frontend → FastAPI Backend → LLaMA 3.2 (dev) / GPT-4o-mini (prod)
                              ↓
                    pgvector (PostgreSQL 16)
                    SentenceTransformers
                    Edge TTS
\`\`\`

## Tech Stack

| Technology | Role |
|-----------|------|
| LLaMA 3.2 / GPT-4o-mini | LLM (local dev / production) |
| SentenceTransformers | Vector embeddings |
| PostgreSQL + pgvector | Relational DB + vector search |
| FastAPI | REST API + SSE streaming |
| React 18 + Vite | Frontend SPA |
| Tailwind CSS | Styling |
| Edge TTS | Voice synthesis (free) |
| Docker Compose | One-command deployment |

## Evaluation Results

| Metric | Value |
|--------|-------|
| Pass rate | —/52 (—%) |
| Emergency accuracy | —/8 |
| Dosage safety | —/8 |
| Avg latency | —ms |

See [eval/report.md](eval/report.md) for details.

## Engineering Decisions

See [DECISIONS.md](DECISIONS.md) — pgvector vs Pinecone, chunk size tuning,
embedding model comparison, refusal policy, and more.

## Project Structure

\`\`\`
pediatricai/
├── backend/         # FastAPI + RAG + TTS + streaming
├── frontend/        # React 18 + Vite + Tailwind
├── db/              # PostgreSQL schema
├── eval/            # 52 test questions + metrics
├── data/guidelines/ # Medical PDFs (not in git)
├── aws/             # Task definitions for ECS
├── scripts/         # Deploy scripts
├── docker-compose.yml
├── DECISIONS.md
└── MEDICAL_DISCLAIMER.md
\`\`\`