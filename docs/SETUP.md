# Developer Setup Guide

## Prerequisites

- **Node.js**: Version 20 or higher (`node -v`)
- **npm**: Bundled with Node.js
- **Python**: Version 3.11 or higher (`python --version`)
- **pip**: Python package manager

## Frontend Setup

```bash
# Navigate to the frontend directory
cd app-qa-team   # or wherever you cloned the repo

# Install dependencies
npm install

# Start the development server
npm run dev
```

The dev server will start at `http://localhost:3001` by default (configured in `vite.config.ts`).

### Build for Production

```bash
npm run build
```

This runs `tsc -b && vite build` and outputs static files to the `dist/` directory.

### Frontend Tests

```bash
# Type-check only (no emit)
npx tsc --noEmit -p tsconfig.app.json

# Build (includes type checking)
npm run build
```

## Backend Setup

```bash
# Navigate to the backend directory
cd trading-bot-backend

# Create a virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Start the API server
python run.py --mode api --host 0.0.0.0 --port 8000
```

The API will be available at:
- API Base: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- Health Check: `GET /health`

### Backend Tests

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_backtest.py
pytest tests/test_engine.py
pytest tests/test_strategies.py
```

## Environment Variables

### Backend (`trading-bot-backend/`)

Create a `.env` file in the backend root or set these directly:

| Variable | Description | Default |
|----------|-------------|---------|
| `BOT_APP__LOG_LEVEL` | Logging level | `INFO` |
| `BOT_API__CORS_ORIGINS` | CORS allowed origins | `["http://localhost:3001"]` |
| `BOT_API__PORT` | API server port | `8000` |
| `BOT_MARKET_DATA__COINGECKO__ENABLED` | Enable CoinGecko | `true` |
| `BOT_RISK__MAX_DRAWDOWN_PCT` | Max drawdown limit | `0.10` |

The backend also reads from `config.yaml` for all structured configuration.

### Frontend

No environment variables are required for local development. The frontend uses `HashRouter` and assumes the backend is at `http://localhost:8000`.

## Troubleshooting

### Frontend Issues

| Issue | Solution |
|-------|----------|
| `npm install` fails | Delete `node_modules` and `package-lock.json`, then run `npm install` again |
| Build fails with TS errors | Run `npx tsc --noEmit -p tsconfig.app.json` to isolate errors |
| Port 3001 in use | Change the port in `vite.config.ts` or run `npm run dev -- --port 3002` |
| Tailwind styles not applied | Ensure `index.css` has `@tailwind` directives and `tailwind.config.js` content paths are correct |

### Backend Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: pydantic_settings` | Run `pip install pydantic-settings` (should be in `requirements.txt`) |
| `ImportError` on startup | Ensure you're running from the `trading-bot-backend/` directory so relative imports resolve |
| CoinGecko rate limit (429) | Wait 1-2 minutes; the cache will serve stale data for 5 minutes |
| Yahoo Finance fails | Check internet connection; yfinance requires network access |
| `FileNotFoundError: config.yaml` | Ensure `config.yaml` exists in the backend root directory |

### Cross-Origin (CORS) Errors

If the frontend cannot reach the backend:
1. Verify `BOT_API__CORS_ORIGINS` includes your frontend URL (e.g., `http://localhost:3001`)
2. Check that the backend is actually running (`curl http://localhost:8000/health`)
3. Ensure the frontend is using the correct API base URL
