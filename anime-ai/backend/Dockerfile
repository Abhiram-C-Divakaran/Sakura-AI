FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install system dependencies needed for runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create dedicated non-root application user
RUN groupadd -g 1001 sakura && \
    useradd -u 1001 -g sakura -s /bin/bash -m sakura

COPY . .
RUN mkdir -p /data/library /workspaces && \
    chown -R sakura:sakura /app /data/library /workspaces && \
    chmod 770 /data/library /workspaces

USER sakura

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
