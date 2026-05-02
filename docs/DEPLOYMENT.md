# Deployment Guide

## Quick Start (Docker Compose)

The fastest way to deploy both frontend and backend together:

```bash
# 1. Set your encryption key
export VOLTANODE_SECRET_KEY="your-secure-random-string"

# 2. Build and start both services
docker-compose up --build -d

# 3. Check health
curl http://localhost:8000/health
# Frontend: http://localhost
# Backend API: http://localhost:8000
```

To stop:
```bash
docker-compose down
```

---

## Manual Deployment

### Frontend

```bash
cd newbuild/app
npm install
npm run build
```

Builds to `newbuild/app/dist/`.

#### Docker (Frontend Only)

```bash
cd newbuild/app
docker build -t voltanode-frontend .
docker run -p 80:80 voltanode-frontend
```

### Backend

```bash
cd trading-bot-backend
pip install -r requirements.txt
python run.py --mode api --host 0.0.0.0 --port 8000
```

#### Docker (Backend Only)

```bash
cd trading-bot-backend
docker build -t voltanode-backend .
docker run -p 8000:8000 -e VOLTANODE_SECRET_KEY=your-key voltanode-backend
```

---

## Production Configuration

Copy and customize the production config:

```bash
cp trading-bot-backend/config.production.yaml trading-bot-backend/config.yaml
# Edit CORS origins, log level, and safety limits
```

Key changes for production:
- `api.cors_origins`: Set to your frontend domain(s) only
- `app.log_level`: Change to `WARNING`
- `app.data_dir`: Use a persistent volume path (`/app/data` in Docker)
- `risk.*`: Tighten limits (examples in `config.production.yaml`)

Environment variables override config values:
- `BOT_API__CORS_ORIGINS`
- `BOT_APP__LOG_LEVEL`
- `BOT_APP__DATA_DIR`
- `VOLTANODE_SECRET_KEY` (required for API key encryption)

---

## Architecture

```
┌─────────────┐      ┌─────────────┐
│   Nginx     │─────▶│  Frontend   │
│   (port 80) │      │  (React)    │
└─────────────┘      └─────────────┘
        │
        │ /api/* proxy
        ▼
┌─────────────┐
│   FastAPI   │
│  (port 8000)│
└─────────────┘
```

---

## Health Checks

- Backend: `GET /health` → `{"status":"ok"}`
- Docker Compose includes automatic health checks

---

## Troubleshooting

**Frontend shows "Backend offline"**
- Check `api.cors_origins` includes your frontend URL
- Verify backend is running: `curl http://localhost:8000/health`

**API keys fail to save**
- Ensure `VOLTANODE_SECRET_KEY` is set
- Check backend logs for encryption errors

**Build fails**
- Use Node 20+: `node --version`
- Clear `node_modules` and reinstall: `rm -rf node_modules && npm install`
