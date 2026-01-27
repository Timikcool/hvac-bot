# HVAC Bot - Deployment Guide

## Deployment Options

| Option | Best For | Cost | Complexity |
|--------|----------|------|------------|
| **Railway** | Quick deploy, auto-scaling | $5-20/mo | ⭐ Easy |
| **Render** | Free tier, simple | $0-25/mo | ⭐ Easy |
| **Fly.io** | Global edge, Docker | $5-20/mo | ⭐⭐ Medium |
| **VPS** | Full control | $5-40/mo | ⭐⭐⭐ Advanced |

---

## Option 1: Railway (Recommended)

### Step 1: Install CLI
```bash
npm install -g @railway/cli
railway login
```

### Step 2: Create Project
```bash
cd hvac_bot
railway init
```

### Step 3: Add Services

Railway auto-detects `docker-compose.yml`. Or add manually:

```bash
# Add PostgreSQL
railway add -d postgres

# Add Redis  
railway add -d redis
```

### Step 4: Set Environment Variables

In Railway dashboard, add:
```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
```

### Step 5: Deploy

```bash
railway up
```

### Step 6: Deploy Frontend to Vercel

```bash
cd frontend
vercel

# Set environment variable
# NEXT_PUBLIC_API_URL=https://your-railway-app.up.railway.app/api
```

---

## Option 2: Render

### Step 1: Create Account
Go to https://render.com and sign up

### Step 2: Create Services

**PostgreSQL:**
- New → PostgreSQL
- Note the connection string

**Redis:**
- New → Redis
- Note the connection string

**Backend:**
- New → Web Service
- Connect your GitHub repo
- Root Directory: `backend`
- Build Command: `pip install -e .`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Environment Variables:**
```
DATABASE_URL=<postgres-connection-string>
REDIS_URL=<redis-connection-string>
QDRANT_HOST=<see-below>
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

**Qdrant (Private Service):**
- New → Private Service
- Docker image: `qdrant/qdrant`
- Port: 6333

### Step 3: Deploy Frontend

- New → Static Site
- Connect GitHub, select `frontend` directory
- Build Command: `npm run build`
- Publish Directory: `out` or `.next`

---

## Option 3: Fly.io

### Step 1: Install CLI
```bash
curl -L https://fly.io/install.sh | sh
fly auth login
```

### Step 2: Launch
```bash
cd hvac_bot
fly launch
```

### Step 3: Create Volumes (for Qdrant data)
```bash
fly volumes create qdrant_data --size 10 --region ord
```

### Step 4: Deploy
```bash
fly deploy
```

### Step 5: Set Secrets
```bash
fly secrets set ANTHROPIC_API_KEY=sk-ant-...
fly secrets set OPENAI_API_KEY=sk-...
```

---

## Option 4: VPS (DigitalOcean, Linode, etc.)

### Step 1: Create Server
- Ubuntu 22.04 LTS
- 2GB+ RAM
- Install Docker

### Step 2: Clone & Configure
```bash
ssh root@your-server

git clone <your-repo> /opt/hvac_bot
cd /opt/hvac_bot

cp backend/.env.example backend/.env
nano backend/.env  # Add your API keys
```

### Step 3: Start Services
```bash
docker-compose up -d
```

### Step 4: Setup Nginx (Reverse Proxy)
```bash
apt install nginx certbot python3-certbot-nginx

# Create config
cat > /etc/nginx/sites-available/hvac << 'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location /api {
        proxy_pass http://localhost:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
    }
}
EOF

ln -s /etc/nginx/sites-available/hvac /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx

# SSL
certbot --nginx -d your-domain.com
```

---

## Restore Qdrant Data

After deploying, restore your books from backup:

### Method 1: Upload via API
Re-upload PDFs through the admin UI or API.

### Method 2: Restore from Snapshot
```bash
# Copy snapshot to server
scp backups/hvac_manuals_*.snapshot user@server:/tmp/

# On server, restore
curl -X POST "http://localhost:6333/collections/hvac_manuals/snapshots/upload" \
  -F "snapshot=@/tmp/hvac_manuals_*.snapshot"
```

---

## Post-Deployment Checklist

- [ ] All services running (`docker-compose ps`)
- [ ] API responding (`curl https://your-domain.com/api/health`)
- [ ] Frontend loading
- [ ] Chat working with sources
- [ ] SSL certificate active
- [ ] Environment variables set correctly
- [ ] Qdrant data restored
- [ ] Backups scheduled

---

## Monitoring

### Health Check Endpoints
```bash
# Backend health
curl https://your-domain.com/api/health

# Qdrant status
curl https://your-domain.com/api/admin/documents
```

### Logs
```bash
# Railway
railway logs

# Docker
docker-compose logs -f

# Fly.io
fly logs
```

---

## Backup Strategy

### Automated Daily Backups
Add to crontab:
```bash
0 2 * * * /opt/hvac_bot/scripts/backup-qdrant.sh >> /var/log/qdrant-backup.log 2>&1
```

### Manual Backup Before Deploy
```bash
./scripts/backup-qdrant.sh
```

---

## Cost Estimates

| Setup | Monthly Cost |
|-------|--------------|
| **Minimal** (Render free tier) | $0 |
| **Basic** (Railway) | $5-15 |
| **Production** (Railway + monitoring) | $20-40 |
| **VPS** (DigitalOcean 2GB) | $12-24 |


