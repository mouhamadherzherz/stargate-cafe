FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libjpeg-dev \
    libfreetype6-dev \
    zlib1g-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /opt/stargate

# Copy requirements and install
COPY requirements.txt /opt/stargate/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . /opt/stargate

# Create uploads directory
RUN mkdir -p /opt/stargate/static/uploads && chown -R root:root /opt/stargate/static/uploads

ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Use a robust production server
CMD ["gunicorn", "-b", "0.0.0.0:5000", "app:app", "--workers", "3", "--threads", "2", "--timeout", "120"]
