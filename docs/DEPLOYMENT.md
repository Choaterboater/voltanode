# Deployment Guide

## Frontend Deployment

### Build the Production Bundle

```bash
cd app-qa-team
npm install
npm run build
```

This creates a `dist/` folder containing:
- `index.html`
- `assets/index-*.js` (bundled JavaScript)
- `assets/index-*.css` (bundled CSS)

### Deployment Targets

#### Static Hosting (Recommended)

The frontend uses `HashRouter`, making it ideal for static file hosts:

**Vercel / Netlify / Cloudflare Pages:**
```bash
# Vercel
npx vercel --prod dist/

# Netlify
npx netlify deploy --prod --dir=dist

# Cloudflare Pages
npx wrangler pages deploy dist/
```

**AWS S3 + CloudFront:**
```bash
aws s3 sync dist/ s3://your-bucket-name --delete
aws cloudfront create-invalidation --distribution-id YOUR_DIST_ID --paths "/*"
```

**GitHub Pages:**
Push the `dist/` folder contents to the `gh-pages` branch or use `gh-pages` npm package.

#### Docker

```dockerfile
# Dockerfile
FROM nginx:alpine
COPY dist/ /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

```nginx
# nginx.conf — SPA fallback for HashRouter
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

### Base Path

The Vite config uses `base: './'` for relative paths. If deploying to a subdirectory, update:

```ts
// vite.config.ts
export default defineConfig({
  base: '/trading-bot/',  // Change if needed
  // ...
});
```

---

## Backend Deployment

### Requirements

- Python 3.11+
- All dependencies from `requirements.txt`
- `config.yaml` in the working directory

### Run with Uvicorn Directly

```bash
cd trading-bot-backend
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

Or use the provided entry point:

```bash
python run.py --mode api --host 0.0.0.0 --port 8000
```

### Docker

```dockerfile
# Dockerfile.backend
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "run.py", "--mode", "api", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
docker build -f Dockerfile.backend -t trading-bot-api .
docker run -p 8000:8000 trading-bot-api
```

### Environment Configuration for Production

Set environment variables or update `config.yaml`:

```yaml
api:
  host: "0.0.0.0"
  port: 8000
  cors_origins:
    - "https://your-frontend-domain.com"
    - "https://app.your-domain.com"

app:
  log_level: "WARNING"
  json_logs: true
  data_dir: "/var/lib/trading-bot/data"

risk:
  max_drawdown_pct: 0.05
  max_position_size_pct: 0.10
```

### Production Checklist

- [ ] Set `BOT_API__CORS_ORIGINS` to your frontend domain(s) only
- [ ] Change default log level from `INFO` to `WARNING`
- [ ] Mount persistent volume for `./data` directory
- [ ] Run behind a reverse proxy (nginx, traefik, or cloud load balancer)
- [ ] Enable HTTPS (Let's Encrypt, Cloudflare, or AWS ACM)
- [ ] Configure firewall rules (only expose 8000 to the reverse proxy)
- [ ] Set up health check monitoring on `/health`
- [ ] Use a process manager (systemd, supervisor, or Kubernetes) for auto-restart

### systemd Service Example

```ini
# /etc/systemd/system/trading-bot.service
[Unit]
Description=Paper Trading Bot API
After=network.target

[Service]
Type=simple
User=tradingbot
WorkingDirectory=/opt/trading-bot-backend
Environment=BOT_API__PORT=8000
Environment=BOT_APP__LOG_LEVEL=WARNING
ExecStart=/opt/trading-bot-backend/venv/bin/python run.py --mode api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-bot
sudo systemctl start trading-bot
```

### Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name api.your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
