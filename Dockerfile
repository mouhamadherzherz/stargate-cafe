FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    libfreetype6-dev \
    zlib1g-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create app directory and non-root user
WORKDIR /opt/stargate

RUN groupadd -r stargate && useradd -r -g stargate -d /opt/stargate stargate

# Copy requirements and install
COPY requirements.txt /opt/stargate/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . /opt/stargate

# Create directories and assign ownership
RUN mkdir -p /opt/stargate/static/uploads /opt/stargate/data \
    && chown -R stargate:stargate /opt/stargate

USER stargate

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1
ENV ENABLE_OTA_CHECKS=0

EXPOSE 5000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/api/check_update', timeout=5)" || exit 1

# Use a robust production server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app", "--workers", "3", "--threads", "2", "--timeout", "120"]
