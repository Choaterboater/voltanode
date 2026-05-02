# Deployment Guide

## Quick Start (Docker Compose)

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
cd app
npm install
npm run build
```

Builds to `app/dist/`.

Serves on `http://localhost:3000` via Vite dev server:
```bash
npm run dev -- --port 3000
```

### Backend

```bash
cd trading-bot-backend
pip install -r requirements.txt
```

Start the API server:
```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Or:
```bash
python run.py
```

---

## Environment Variables

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `VOLTANODE_SECRET_KEY` | Fernet key for API encryption (generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) | `abcd1234...` |

### Optional — News & Sentiment

| Variable | Description | Default |
|----------|-------------|---------|
| `ALPACA_API_KEY` | Alpaca News API key | — |
| `ALPACA_SECRET_KEY` | Alpaca News API secret | — |
| `LLM_PROVIDER` | LLM for sentiment (`ollama`, `kimi`, `claude`, `openai`) | — |
| `LLM_MODEL` | Model name (`llama3.2:3b`, `gpt-3.5-turbo`, etc.) | — |
| `LLM_API_KEY` | API key for cloud LLM providers | — |
| `SENTIMENT_HYBRID_MODE` | Use hybrid VADER+LLM (`true`/`false`) | `true` |
| `SENTIMENT_HYBRID_THRESHOLD` | VADER confidence below this triggers LLM | `0.6` |

### Optional — Live Trading

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_BASE_URL` | Base URL for OpenRouter/Groq | `https://api.openai.com/v1` |

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
- `VOLTANODE_SECRET_KEY`

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

**Ollama not available**
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Ensure `LLM_PROVIDER=ollama` is set

**Build fails**
- Use Node 20+: `node --version`
- Clear `node_modules` and reinstall: `rm -rf node_modules && npm install`
