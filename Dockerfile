# Production-Ready Dockerfile for STARGATE CAFE POS & ERP
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/stargate

# Install system dependencies for Pillow, SQLite, and network healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    libjpeg62-turbo-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create non-root user and ensure directories exist
RUN useradd -m -u 1001 stargate && \
    mkdir -p data logs Safe_Backups static/uploads && \
    chown -R stargate:stargate /opt/stargate

USER stargate

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:5000/api/check_update || exit 1

CMD ["python", "app.py"]
