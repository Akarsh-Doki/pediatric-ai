# 👨‍⚕️ PediatricAI
 
**An AI-powered pediatric health assistant with RAG-grounded medical responses, animated doctor interface, and voice synthesis.**
 
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white)](https://reactjs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16_+_pgvector-4169E1?logo=postgresql&logoColor=white)](https://postgresql.org)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?logo=openai&logoColor=white)](https://openai.com)
[![AWS](https://img.shields.io/badge/AWS-ECS_|_RDS_|_CloudFront-FF9900?logo=amazonaws&logoColor=white)](https://aws.amazon.com)
[![Tests](https://img.shields.io/badge/Tests-59_passing-brightgreen?logo=pytest&logoColor=white)](tests/)
 
---

## What is this?
 
Parents with sick children often turn to the internet at 2am, finding conflicting information from unreliable sources. PediatricAI provides evidence-based pediatric guidance grounded in medical literature, with clear citations so parents can verify every recommendation.
 
A parent types "my child has a 102°F fever and won't eat." PediatricAI retrieves relevant medical guidelines from its corpus, generates a structured response (what it likely is → what to do now → when to call the doctor), speaks the answer aloud, and shows which medical sources it used — all in under 5 seconds.
 
---

> **⚠️ Medical Disclaimer:** PediatricAI is a portfolio project for educational purposes. It is not a substitute for professional medical advice, diagnosis, or treatment. Always consult a qualified healthcare provider for medical concerns.
 
---

## 🎬 Demo
 
<!-- Replace this with your actual demo GIF -->
<!-- To record: use macOS screen recording or Loom, convert to GIF with gifski or ezgif.com -->
<!-- Recommended: 800x500px, 10-15 seconds, showing a question → streaming answer → doctor animation -->
 
[![PediatricAI Preview](https://img.youtube.com/vi/OTv25-CvAow/maxresdefault.jpg)](https://www.youtube.com/watch?v=OTv25-CvAow)
 
**[➡️ Try the live app](https://d1c7nhfv15encr.cloudfront.net)**
 
---
 
## Architecture
 
```
Parent asks: "My child has a 102°F fever"
  ↓
CloudFront — serves React frontend over HTTPS from S3
  ↓
ALB — routes API requests to the backend container
  ↓
ECS Fargate — runs FastAPI in Docker (serverless)
  ↓  1. Check if the question is too vague
  ↓  2. Convert question to 384-dim vector
  ↓  3. Search pgvector for matching medical chunks
  ↓  4. Score confidence: refuse / fallback / answer
  ↓  5. Send chunks + question to GPT-4o-mini
  ↓  6. Stream response tokens back via SSE
  ↓
RDS PostgreSQL — stores 274 medical chunks with pgvector
  ↓
OpenAI GPT-4o-mini — generates the medical response
  ↓
Doctor answers with citations, animated face, and voice
```
 
---

## Features
 
### RAG Pipeline (Retrieval-Augmented Generation)
- **12 medical PDFs** ingested into 274 chunks with 100-token overlap
- **Sentence embeddings** using all-MiniLM-L6-v2 (384 dimensions)
- **pgvector cosine similarity** search with configurable thresholds
- **Confidence bands**: 0.55+ = high confidence, 0.45-0.55 = general knowledge fallback, <0.45 = refusal
- **Citations** showing which medical source supported each answer
### Safety & Intelligence
- **Ambiguity detection** — catches vague queries ("my child is sick") before wasting compute on bad embeddings, asks targeted follow-up questions
- **Emergency detection** — "Call 911 right now" appears first for choking, seizures, poisoning
- **Rate limiting** — 15 queries/hour per IP (slowapi) to protect the OpenAI budget
- **Input validation** — 5,000 character limit with live counter
- **Error boundary** — React error boundary prevents white-screen crashes
### Animated Doctor Interface
- **11 expression PNGs** — idle (with blink variants), thinking, talking (4 mouth positions), concerned, reassuring
- **Context-aware expressions** — thinking while waiting, talking during streaming, concerned for urgent symptoms
- **Browser speech synthesis** — male voice reads responses aloud at 1.35x speed
- **Stop/replay controls** — pause the doctor mid-sentence, replay the last response
### Production Infrastructure
- **AWS ECS Fargate** — serverless container running the FastAPI backend
- **RDS PostgreSQL 16** with pgvector extension
- **CloudFront + S3** — frontend served globally over HTTPS
- **Secrets Manager** — API keys encrypted at rest, injected at runtime
- **CI/CD** — GitHub Actions runs 59 tests → deploys to ECR + S3 on every push
- **Start/stop scripts** — `start.sh` brings everything up in 5 minutes, `stop.sh` shuts it down in 30 seconds

---
 
## Tech Stack
 
| Layer | Technology | Why |
|-------|-----------|-----|
| **Frontend** | React 18, Vite, Tailwind CSS | Fast builds, utility-first styling, modern React hooks |
| **Backend** | FastAPI, Python 3.11 | Async support for streaming, automatic OpenAPI docs |
| **Database** | PostgreSQL 16 + pgvector | Vector similarity search natively in SQL |
| **Embeddings** | all-MiniLM-L6-v2 (384d) | Fast, accurate sentence embeddings without GPU |
| **LLM** | GPT-4o-mini (OpenAI) | Best quality/cost ratio, follows system prompts reliably |
| **Streaming** | Server-Sent Events (SSE) | Real-time token delivery, simpler than WebSockets |
| **TTS** | Browser SpeechSynthesis API | Free, instant, no API calls needed |
| **Infrastructure** | AWS ECS, ALB, RDS, S3, CloudFront | Production-grade, scalable, cost-controlled |
| **CI/CD** | GitHub Actions | Auto-deploy on push, test gating |
| **Testing** | pytest (59 tests) | Unit tests for evaluation, clarification, symptoms, generation |
 
---

## How the RAG Pipeline Works
 
When a parent asks a question, here's what happens in ~3 seconds:
 
**1. Ambiguity check** — Before doing any work, the system checks if the query is too vague. "My child is sick" gets a follow-up question asking for specifics. "My child has a 102°F fever" passes through immediately.
 
**2. Symptom extraction** — Keywords are extracted for analytics: "fever", "loss_of_appetite", "cough". Severity is estimated from urgency words.
 
**3. Embedding** — The question is converted into a 384-dimensional vector using SentenceTransformers (all-MiniLM-L6-v2). This captures semantic meaning — "burning up" maps close to "fever" in vector space.
 
**4. Retrieval** — pgvector performs cosine similarity search across 274 medical chunks. Returns the top 5 most relevant chunks with similarity scores.
 
**5. Confidence scoring** — A weighted formula (0.6 × best_score + 0.4 × average_score) determines response confidence:
  - **≥ 0.55**: High confidence — answer grounded in medical corpus
  - **0.45–0.55**: Moderate — supplement with general knowledge
  - **< 0.45**: Low — refuse gracefully with referral to pediatrician
**6. Prompt assembly** — System prompt + patient info (name, age, conditions) + retrieved chunks + conversation history (last 6 messages) + user question → sent to GPT-4o-mini.
 
**7. Streaming generation** — GPT-4o-mini streams tokens via SSE. Each token appears in the chat immediately. The doctor face animates its mouth during streaming.
 
**8. Post-processing** — A dictionary-based word fixer (130,000+ English words + medical terms) catches any broken words from PDF extraction artifacts.
 
---

## Test Results
 
59 tests across 4 modules, all passing:
 
| Module | Tests | What it covers |
|--------|-------|---------------|
| `test_evaluation.py` | 14 | Refusal thresholds, confidence formula, boundary cases at 0.45 |
| `test_clarification.py` | 16 | Specific queries pass through, vague queries caught, greetings handled |
| `test_symptoms.py` | 13 | Keyword extraction accuracy, severity classification |
| `test_generation.py` | 12 | Prompt assembly, patient info inclusion, history limits, urgency detection |
 
```bash
python -m pytest tests/ -v
# ========================= 59 passed =========================
```
 
---

## Local Development Setup
 
### Prerequisites
- macOS or Linux
- Python 3.11 (via conda or pyenv)
- Node.js 20+
- Docker Desktop
- An OpenAI API key ($5 credit lasts months)
### Quick start
 
```bash
# 1. Clone and enter
git clone https://github.com/Akarsh-Doki/pediatric-ai.git
cd pediatric-ai
 
# 2. Start the database
docker compose up db -d
 
# 3. Backend setup
conda create -n pediatricai python=3.11 -y
conda activate pediatricai
pip install -r backend/requirements.txt
 
# 4. Configure environment
cp .env.example .env
# Edit .env: add your OpenAI API key
 
# 5. Ingest medical corpus
python -m backend.scripts.ingest_corpus
 
# 6. Start backend
python -m uvicorn backend.main:app --reload --port 8000
 
# 7. Frontend (new terminal)
cd frontend
npm install
npm run dev
 
# 8. Open http://localhost:5173
```
 
### Run tests
 
```bash
python -m pytest tests/ -v
```

---

## AWS Deployment
 
The project is deployed on production AWS infrastructure:
 
| Service | Purpose |
|---------|---------|
| **ECS Fargate** | Runs the backend Docker container (0.5 vCPU, 1GB RAM) |
| **ALB** | Routes traffic, health checks, stable endpoint |
| **RDS** | PostgreSQL 16 with pgvector, stores 274 medical chunks |
| **S3 + CloudFront** | Serves React frontend globally over HTTPS |
| **Secrets Manager** | Encrypted storage for API keys |
| **ECR** | Docker image repository |
 
### Cost management
 
Start/stop scripts control costs:
 
```bash
./aws-scripts/start.sh      # Start everything (~5 min, ~$1/day while on)
./aws-scripts/stop.sh        # Stop everything (~30 sec, ~$0.50/month while off)
./aws-scripts/hibernate.sh   # Deep stop ($0.00/month)
./aws-scripts/status.sh      # Check what's running
```
 
---
 
## Project Structure
 
```
pediatric-ai/
├── backend/
│   ├── config.py                  # Settings (reads .env)
│   ├── main.py                    # FastAPI app, CORS, rate limiting
│   ├── models/
│   │   ├── database.py            # 7 SQLAlchemy tables
│   │   └── schemas.py             # Pydantic request/response models
│   ├── routers/
│   │   ├── chat.py                # /chat/query + /chat/stream (SSE)
│   │   ├── patients.py            # CRUD for patient records
│   │   ├── documents.py           # PDF upload + live ingestion
│   │   └── tts.py                 # Text-to-speech endpoint
│   ├── services/
│   │   ├── generation.py          # LLM prompt building + streaming + word fixer
│   │   ├── retrieval.py           # pgvector cosine similarity search
│   │   ├── evaluation.py          # Confidence scoring + refusal logic
│   │   ├── clarification.py       # Ambiguity detection
│   │   ├── ingestion.py           # PDF → chunks → embeddings
│   │   └── tts_service.py         # Google TTS (backend fallback)
│   ├── utils/
│   │   ├── symptoms.py            # Keyword-based symptom extraction
│   │   ├── embeddings.py          # SentenceTransformer wrapper
│   │   └── chunking.py            # 600-token chunks, 100 overlap
│   └── scripts/
│       └── ingest_corpus.py       # Bulk PDF ingestion
├── frontend/
│   └── src/
│       ├── App.jsx                # Main app with doctor animation
│       ├── hooks/
│       │   ├── useChat.js         # SSE streaming + state management
│       │   ├── useAudioSync.js    # Browser speech synthesis
│       │   └── useTheme.jsx       # Dark/light mode
│       └── components/
│           ├── ChatInterface.jsx  # Message bubbles, skeleton loading
│           ├── DoctorFace.jsx     # 11-PNG expression animation
│           ├── ErrorBoundary.jsx  # Crash recovery
│           ├── CitationPanel.jsx  # Source references
│           └── Sidebar.jsx        # Patient selection, settings
├── tests/
│   ├── test_evaluation.py         # 14 tests: thresholds, confidence
│   ├── test_clarification.py      # 16 tests: ambiguity detection
│   ├── test_symptoms.py           # 13 tests: keyword extraction
│   └── test_generation.py         # 12 tests: prompt assembly
├── aws-scripts/                   # Start/stop/hibernate/teardown
├── data/pdfs/                     # 12 medical PDFs (corpus)
├── .github/workflows/deploy.yml   # CI/CD pipeline
├── docker-compose.yml             # Local full-stack
└── .env.example                   # Environment template
```
 
---

## Key Design Decisions
 
| Decision | Choice | Why |
|----------|--------|-----|
| RAG vs fine-tuning | RAG | Update medical guidelines by swapping PDFs, not retraining. Provides citations. |
| GPT-4o-mini vs larger models | GPT-4o-mini | $0.002/query. Follows system prompts perfectly. Best quality/cost ratio. |
| pgvector vs Pinecone/Weaviate | pgvector | No additional service to manage. Lives in the same PostgreSQL as patient data. |
| Browser TTS vs cloud TTS | Browser | Free, instant, no API latency. Works offline. |
| ECS Fargate vs EC2 | Fargate | No servers to patch. Scales to zero when not in use. |
| Confidence bands vs binary | Bands | Gradual degradation instead of hard refuse. 0.45-0.55 uses general knowledge as fallback. |
 
---
 
## What I'd Improve at Scale
 
- Replace keyword symptom extraction with a medical NER model (SciSpacy/BioBERT)
- Add HTTPS on ALB with ACM certificates
- Multi-language support (Spanish is the most-requested)
- Image upload for rash identification (GPT-4o vision)
- Conversation export to PDF for pediatrician visits
---
 
## Author
 
**Akarsh Doki**
- GitHub: [@Akarsh-Doki](https://github.com/Akarsh-Doki)
- LinkedIn: [linkedin.com/in/akarsh-doki](https://linkedin.com/in/akarsh-doki)
Built from scratch — full-stack AI engineering from RAG pipeline design to production AWS deployment.
