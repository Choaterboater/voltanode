# Backend — Python FastAPI
FROM python:3.11-slim

WORKDIR /app

# Install system deps for pandas/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory
RUN mkdir -p /app/data/cache

EXPOSE 8000

CMD ["python", "run.py", "--mode", "api", "--host", "0.0.0.0", "--port", "8000"]
