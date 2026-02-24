# HVAC AI Assistant Backend

AI-powered assistant for HVAC technicians with RAG-based document retrieval, probability-ordered diagnostics, field terminology mapping, and self-improving feedback loops.

## Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Run migrations
alembic upgrade head

# Start server
uvicorn main:app --reload
```

## Environment Variables

Copy `.env.example` to `.env` and configure:

- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string
- `ANTHROPIC_API_KEY`: Claude API key
- `VOYAGE_API_KEY`: Voyage AI embeddings key
- `OPENCLAW_SHARED_SECRET`: Shared secret for OpenClaw gateway (optional)

## Architecture

The backend is organized into the following service layers:

**RAG Pipeline** (`services/rag/`): Query processing, multi-stage retrieval with diagnostic re-ranking, grounded response generation with terminology post-processing, and anti-hallucination guardrails.

**Diagnostic Engine** (`services/rag/diagnostic_engine.py`): Probability-ordered troubleshooting flowcharts that supplement RAG retrieval. Steps are ordered by failure likelihood (most common cause first) and weights adjust based on technician feedback.

**Terminology Mapper** (`services/rag/terminology.py`): Converts textbook terms to field-standard HVAC language. Includes ~50 seed mappings and learns from corrections.

**Self-Improvement** (`services/improvement/`): Detects in-chat corrections, extracts structured feedback, and applies updates to terminology mappings and diagnostic step priorities.

**OpenClaw Integration** (`services/openclaw/`, `api/openclaw_routes.py`): Webhook endpoints for the OpenClaw messaging gateway with cross-platform user identity sync.

## Testing

```bash
pytest tests/ -v
```

## API Routes

- `POST /api/chat` - Main chat endpoint
- `POST /api/scan-equipment` - Nameplate scanning
- `POST /api/analyze-image` - Visual problem diagnosis
- `POST /api/feedback` - Feedback with correction support
- `POST /api/openclaw/chat` - OpenClaw webhook
- `GET /api/admin/diagnostic-flowcharts` - Manage diagnostics
- `GET /api/admin/terminology` - Manage terminology
- `GET /api/admin/corrections/pending` - Review corrections
- `GET /api/admin/improvement-report` - Improvement stats
