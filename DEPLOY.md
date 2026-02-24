# HVAC Bot - Deployment Guide

## Current Production Setup (Railway)

All services deployed to Railway for low-latency internal communication:

| Service | URL | Status |
|---------|-----|--------|
| **Frontend** | https://hvac-frontend-production.up.railway.app | ✅ |
| **Backend API** | https://hvac-api-production.up.railway.app | ✅ |
| **PostgreSQL** | postgres.railway.internal:5432 | ✅ |
| **Redis** | redis.railway.internal:6379 | ✅ |
| **Qdrant** | qdrant.railway.internal:6333 | ✅ |

### Internal Communication
All services communicate via Railway's private network (`*.railway.internal`) for:
- **Zero egress costs** - internal traffic is free
- **Low latency** - ~1ms between services
- **Security** - no public exposure for databases

---

## Quick Deploy (Railway)

### Prerequisites
- Railway account: https://railway.com
- Railway CLI installed: `brew install railway`
- GitHub repo with code

### Step 1: Login & Create Project
```bash
railway login
cd hvac_bot
railway init
```

### Step 2: Deploy Database Services
```bash
# PostgreSQL
railway add -d postgres

# Redis  
railway add -d redis
```

Or use templates:
```bash
railway deploy-template --search "PostgreSQL"
railway deploy-template --search "Redis"
railway deploy-template --search "Qdrant"
```

### Step 3: Create Backend Service
```bash
railway add -s hvac-api
railway link -s hvac-api
```

### Step 4: Set Environment Variables
```bash
railway variables set \
  DATABASE_URL="postgresql+asyncpg://postgres:PASSWORD@postgres.railway.internal:5432/railway" \
  REDIS_URL="redis://default:PASSWORD@redis.railway.internal:6379" \
  QDRANT_HOST="qdrant.railway.internal" \
  QDRANT_PORT="6333" \
  ANTHROPIC_API_KEY="sk-ant-..." \
  OPENAI_API_KEY="sk-proj-..." \
  GOOGLE_API_KEY="..." \
  ENVIRONMENT="production"
```

### Step 5: Deploy Backend
```bash
railway up --service hvac-api
railway domain --service hvac-api  # Generate public URL
```

### Step 6: Create & Deploy Frontend
```bash
railway add -s hvac-frontend
railway link -s hvac-frontend

railway variables set \
  NEXT_PUBLIC_API_URL="https://hvac-api-production.up.railway.app" \
  PORT="3000"

cd frontend
railway up --service hvac-frontend
railway domain --service hvac-frontend
```

### Step 7: Update CORS
Add frontend URL to backend CORS:
```bash
railway variables set -s hvac-api \
  CORS_ORIGINS="http://localhost:3000,https://hvac-frontend-production.up.railway.app"
```

---

## Migrate Local Data to Railway

### Migrate Qdrant Vectors
```bash
python scripts/migrate-qdrant.py
```

This script:
1. Connects to local Qdrant (localhost:6333)
2. Exports all vectors from `hvac_manuals` collection
3. Creates collection on Railway Qdrant
4. Uploads all vectors in batches

### Migrate PostgreSQL (Conversations)
```bash
# Export from local
pg_dump -h localhost -U postgres hvac_assistant > backup.sql

# Import to Railway (get connection string from Railway dashboard)
psql "postgresql://postgres:PASSWORD@PUBLIC_HOST:PORT/railway" < backup.sql
```

---

## Environment Variables Reference

### Required
| Variable | Description | Example |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection (asyncpg) | `postgresql+asyncpg://...` |
| `REDIS_URL` | Redis connection | `redis://...` |
| `QDRANT_HOST` | Qdrant hostname | `qdrant.railway.internal` |
| `ANTHROPIC_API_KEY` | Claude API key | `sk-ant-...` |
| `OPENAI_API_KEY` | OpenAI API key | `sk-proj-...` |

### Optional
| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Gemini API key | - |
| `GCP_PROJECT_ID` | GCP project | - |
| `ENVIRONMENT` | production/development | `development` |
| `LOG_LEVEL` | INFO/DEBUG/WARNING | `INFO` |
| `CORS_ORIGINS` | Allowed origins (comma-sep) | `http://localhost:3000` |

---

## Deploy OpenClaw Gateway (Optional)

The OpenClaw gateway enables Telegram and WhatsApp messaging channels.

### Step 1: Set OpenClaw Environment Variables
```bash
railway variables set -s openclaw \
  ANTHROPIC_API_KEY="sk-ant-..." \
  HVAC_BACKEND_URL="https://hvac-api-production.up.railway.app" \
  OPENCLAW_SHARED_SECRET="your-shared-secret" \
  TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
```

### Step 2: Set Backend Secret (must match)
```bash
railway variables set -s hvac-api \
  OPENCLAW_SHARED_SECRET="your-shared-secret"
```

### Step 3: Deploy
```bash
cd openclaw
railway up --service openclaw
```

### New Admin Endpoints
After deployment, the following new endpoints are available:

- `GET /api/admin/diagnostic-flowcharts` - List diagnostic flowcharts
- `POST /api/admin/diagnostic-flowcharts` - Create flowchart
- `GET /api/admin/terminology` - List terminology mappings
- `POST /api/admin/terminology` - Add terminology mapping
- `GET /api/admin/corrections/pending` - Review pending corrections
- `POST /api/admin/corrections/{id}/apply` - Approve a correction
- `GET /api/admin/improvement-report` - Weekly improvement stats

---

## Alternative Deployments

### Render
See `render.yaml` for Blueprint deployment:
```bash
# Deploy from GitHub
# Connect repo → Render auto-detects render.yaml
```

### Docker Compose (Local/VPS)
```bash
docker-compose up -d
```

### Vercel (Frontend Only)
```bash
cd frontend
vercel --prod
# Set NEXT_PUBLIC_API_URL to backend URL
```

---

## Monitoring & Logs

```bash
# Railway logs
railway logs -s hvac-api
railway logs -s hvac-frontend

# Health checks
curl https://hvac-api-production.up.railway.app/api/health
curl https://hvac-api-production.up.railway.app/api/admin/manuals
```

---

## Cost Estimate (Railway)

| Service | Plan | Cost |
|---------|------|------|
| Backend | Starter | ~$5/mo |
| Frontend | Starter | ~$5/mo |
| PostgreSQL | Free | $0 |
| Redis | Free | $0 |
| Qdrant | Starter | ~$5/mo |
| **Total** | | **~$15/mo** |

*Railway offers $5 free credit/month for hobby projects.*
