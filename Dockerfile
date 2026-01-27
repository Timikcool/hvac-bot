FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including libpq for psycopg2
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy backend requirements first for caching
COPY backend/requirements.txt ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code (cache bust v2 - CORS fix)
COPY backend/ ./

# Create necessary directories
RUN mkdir -p uploads checkpoints logs

# Expose port
EXPOSE 8000

# Run migrations and start the application (Railway injects PORT env variable)
CMD alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
