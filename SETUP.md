# HVAC Bot - Setup Guide

## Prerequisites

- **Docker Desktop** - [Install](https://www.docker.com/products/docker-desktop/)
- **Node.js 18+** - [Install](https://nodejs.org/)
- **Python 3.11+** - [Install](https://www.python.org/)
- **API Keys**:
  - Anthropic (required) - [Get key](https://console.anthropic.com/)
  - OpenAI (required for embeddings) - [Get key](https://platform.openai.com/)
  - Google AI (optional, for Gemini) - [Get key](https://aistudio.google.com/)

---

## Quick Start (5 minutes)

### 1. Clone & Configure

```bash
git clone <your-repo-url>
cd hvac_bot

# Create environment file
cp backend/.env.example backend/.env
```

Edit `backend/.env` and add your API keys:
```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...  # Optional
```

### 2. Start Infrastructure

```bash
./scripts/deploy.sh local
```

This starts PostgreSQL, Redis, and Qdrant in Docker.

### 3. Setup Backend

```bash
cd backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e .

# Run database migrations
alembic upgrade head

# Start backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Setup Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start frontend
npm run dev
```

### 5. Access the App

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Qdrant Dashboard**: http://localhost:6333/dashboard

---

## Upload Documents

### Via Web UI
1. Go to http://localhost:3000
2. Navigate to Admin → Upload Documents
3. Select PDF file, enter title, choose type (manual/book)
4. Click Upload

### Via API
```bash
curl -X POST http://localhost:8000/api/admin/documents/upload \
  -F "file=@your-manual.pdf" \
  -F "title=HVAC Fundamentals" \
  -F "document_type=book" \
  -F "use_vision=true"
```

---

## Daily Development

```bash
# Terminal 1: Start infrastructure (if not running)
./scripts/deploy.sh local

# Terminal 2: Backend
cd backend && source .venv/bin/activate && uvicorn main:app --reload

# Terminal 3: Frontend
cd frontend && npm run dev
```

---

## Useful Commands

| Command | Description |
|---------|-------------|
| `./scripts/deploy.sh local` | Start Docker services |
| `./scripts/deploy.sh status` | Check service health & stats |
| `./scripts/deploy.sh backup` | Create Qdrant backup |
| `./scripts/deploy.sh stop` | Stop all services |
| `./scripts/deploy.sh logs` | View Docker logs |

---

## Project Structure

```
hvac_bot/
├── backend/
│   ├── .env                 # API keys & config
│   ├── main.py              # FastAPI application
│   ├── api/
│   │   ├── routes.py        # Chat, feedback, image endpoints
│   │   ├── admin_routes.py  # Admin: diagnostics, terminology, corrections
│   │   └── openclaw_routes.py # OpenClaw webhook endpoints
│   ├── models/
│   │   ├── user.py          # User model (+ Telegram/WhatsApp IDs)
│   │   ├── conversation.py  # Messages, feedback
│   │   └── diagnostic.py    # Flowcharts, steps, terminology, corrections
│   ├── services/
│   │   ├── rag/
│   │   │   ├── pipeline.py          # Main RAG pipeline
│   │   │   ├── retriever.py         # Multi-stage retrieval + diagnostic re-ranking
│   │   │   ├── generator.py         # Grounded response generation
│   │   │   ├── query_processor.py   # Intent detection (+ correction intent)
│   │   │   ├── terminology.py       # Field terminology mapper
│   │   │   └── diagnostic_engine.py # Probability-ordered diagnostics
│   │   ├── improvement/
│   │   │   ├── correction_processor.py # In-chat correction detection
│   │   │   └── feedback_aggregator.py  # Feedback analysis & reports
│   │   ├── openclaw/
│   │   │   └── user_sync.py  # Cross-platform user identity
│   │   ├── ingestion/        # Document parsing
│   │   └── gcp/              # Google Cloud services
│   ├── tests/                # Unit tests
│   └── data/
│       └── manuals/          # Uploaded PDFs
├── frontend/
│   ├── components/           # React components
│   ├── api/                  # API client
│   └── hooks/                # Custom hooks
├── openclaw/                  # OpenClaw messaging gateway
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── config.yaml
│   └── workspace/
│       ├── SOUL.md           # HVAC personality definition
│       └── skills/           # OpenClaw skill definitions
├── scripts/
│   ├── deploy.sh             # Deployment helper
│   ├── backup-qdrant.sh      # Backup script
│   └── migrate-to-cloud.sh   # Cloud migration
├── docker-compose.yml         # Infrastructure
└── SETUP.md                   # This file
```

---

## Troubleshooting

### Port already in use
```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Kill process on port 3000
lsof -ti:3000 | xargs kill -9
```

### Docker services not starting
```bash
# Check Docker is running
docker ps

# Restart services
./scripts/deploy.sh stop
./scripts/deploy.sh local
```

### Database migration errors
```bash
cd backend
source .venv/bin/activate
alembic upgrade head
```

### Qdrant collection issues
```bash
# Check Qdrant status
curl http://localhost:6333/collections/hvac_manuals | jq
```

---

## Running Tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

---

## New Features (v2)

The following features were added in the diagnostic quality & self-improvement update:

**Diagnostic Engine** - Probability-ordered troubleshooting flowcharts that present the most likely cause first, supplementing RAG retrieval with expert-curated diagnostic paths.

**Field Terminology Mapper** - Automatically converts textbook language (e.g., "relay contacts") to field-standard terminology (e.g., "contactor") in both queries and responses. Includes ~50 seed mappings and learns from technician corrections.

**Self-Improvement System** - Detects in-chat corrections from technicians (e.g., "that's wrong, check the contactor first") and applies them to improve future responses by updating terminology mappings and diagnostic step priorities.

**OpenClaw Integration** - Messaging gateway for Telegram and WhatsApp access with persistent per-user memory and HVAC-specific personality.

**Admin Endpoints** - Management of diagnostic flowcharts, terminology mappings, and pending corrections via `/admin/` API routes.
