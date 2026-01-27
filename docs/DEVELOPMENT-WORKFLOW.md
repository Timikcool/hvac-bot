# Development Workflow: Local → Cloud

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DEVELOPMENT CYCLE                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   LOCAL DEVELOPMENT                        CLOUD PRODUCTION              │
│   ┌─────────────────────┐                  ┌─────────────────────┐      │
│   │  • Add new books    │                  │  • Vercel (Frontend)│      │
│   │  • Tune prompts     │   migrate.sh     │  • Railway (Backend)│      │
│   │  • Test changes     │  ─────────────▶  │  • Qdrant Cloud     │      │
│   │  • Debug issues     │   (merge mode)   │  • Supabase (DB)    │      │
│   └─────────────────────┘                  └─────────────────────┘      │
│                                                                          │
│   Key: Cloud data is PRESERVED. Only NEW documents/conversations sync.   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. First-Time Setup

```bash
# Create cloud configuration
./scripts/migrate-to-cloud.sh config
```

Edit `.cloud-config` with your cloud credentials:
- **Qdrant Cloud**: https://cloud.qdrant.io (free 1GB tier)
- **Supabase**: https://supabase.com (free PostgreSQL)
- **Railway/Render**: For backend hosting

### 2. Daily Development (Local)

```bash
# Start local services
docker-compose up -d  # PostgreSQL, Redis, Qdrant

# Start backend
cd backend && source .venv/bin/activate && uvicorn main:app --reload

# Start frontend
cd frontend && npm run dev
```

Work locally:
- Upload new manuals/books via `/admin/documents/upload`
- Test chat responses
- Tune prompts in `backend/services/rag/generator.py`
- Add/modify guardrails

### 3. Push to Cloud (When Ready)

```bash
# Check current status (compare local vs cloud)
./scripts/migrate-to-cloud.sh status

# Sync new documents/conversations (MERGE mode - default)
./scripts/migrate-to-cloud.sh all

# Preview what would sync without making changes
./scripts/migrate-to-cloud.sh all --dry-run

# Sync specific components
./scripts/migrate-to-cloud.sh qdrant    # Just vectors (new documents only)
./scripts/migrate-to-cloud.sh postgres  # Just database (new conversations only)

# Full replace (DESTRUCTIVE - use with caution!)
./scripts/migrate-to-cloud.sh all --replace
```

### Sync Modes

| Mode | Command | Behavior |
|------|---------|----------|
| **Merge** (default) | `./scripts/migrate-to-cloud.sh all` | Only syncs NEW documents/conversations. Cloud data preserved. |
| **Replace** | `./scripts/migrate-to-cloud.sh all --replace` | Overwrites ALL cloud data. Creates backup first. |
| **Dry Run** | `./scripts/migrate-to-cloud.sh all --dry-run` | Shows what would sync without making changes. |

## What Gets Synced

| Component | Local | Cloud | Merge Behavior |
|-----------|-------|-------|----------------|
| **Qdrant** | localhost:6333 | Qdrant Cloud | New documents only (by document_id). Existing cloud vectors preserved. |
| **PostgreSQL** | localhost:5432 | Supabase/Railway | New conversations only. Cloud feedback/history preserved. |
| **Redis** | localhost:6379 | Upstash (optional) | Not synced (ephemeral session cache) |

**Important**: By default, the script uses MERGE mode. Cloud data is never deleted unless you explicitly use `--replace`.

## Cloud Setup Guide

### Qdrant Cloud (Free Tier)

1. Go to https://cloud.qdrant.io
2. Create a free cluster (1GB storage)
3. Get your:
   - **URL**: `https://xxx.us-east4-0.gcp.cloud.qdrant.io:6333`
   - **API Key**: From dashboard

### Supabase (PostgreSQL)

1. Go to https://supabase.com
2. Create a new project
3. Go to Settings → Database → Connection string
4. Use the **URI** format: `postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres`

### Backend Hosting (Railway)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Deploy
cd backend
railway login
railway init
railway up

# Set environment variables in Railway dashboard
```

### Frontend Hosting (Vercel)

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy
cd frontend
vercel

# Set NEXT_PUBLIC_API_URL to your Railway backend URL
```

## Backup Strategy

The migration script automatically keeps backups:

```
backups/
├── hvac_manuals_20260127_143022.snapshot  # Qdrant snapshots
├── hvac_manuals_20260126_102315.snapshot
├── hvac_bot_20260127_143022.sql           # PostgreSQL dumps
└── hvac_bot_20260126_102315.sql
```

Configure retention in `.cloud-config`:
```bash
KEEP_BACKUPS=5  # Keep last 5 backups
```

## Rollback

If something goes wrong:

```bash
# Restore Qdrant from backup
curl -X POST "http://localhost:6333/collections/hvac_manuals/snapshots/upload" \
  -F "snapshot=@backups/hvac_manuals_TIMESTAMP.snapshot"

# Restore PostgreSQL from backup
psql $DATABASE_URL < backups/hvac_bot_TIMESTAMP.sql
```

## Cost Estimates

| Service | Free Tier | Paid |
|---------|-----------|------|
| Qdrant Cloud | 1GB | $25/mo for 4GB |
| Supabase | 500MB DB | $25/mo |
| Railway | $5 credit/mo | ~$5-10/mo |
| Vercel | Unlimited | Free |
| **Total** | **$0** | **~$30-60/mo** |

## Tips

1. **Always test locally first** - Don't push broken changes
2. **Use `status` command** - Check sync state before migrating
3. **Keep backups** - Script does this automatically
4. **Migrate during low traffic** - Qdrant migration briefly locks collection

