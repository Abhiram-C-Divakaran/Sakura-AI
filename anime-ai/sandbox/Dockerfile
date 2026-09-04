# Sakura AI — Dedicated Production Sandbox Execution Environment
# Minimal, hardened container image for isolated repository-level coding tasks.
# Includes: Python 3.11, pip, Git, Node.js LTS, npm, build tools.
# Does NOT contain backend secrets or API keys.

FROM python:3.11-slim

# Install system dependencies, git, curl, build essentials
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    build-essential \
    procps \
    tar \
    gzip \
    unzip \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g npm@latest \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install standard build/test runners
RUN pip install --no-cache-dir --upgrade pip setuptools wheel pytest

# Create non-root unprivileged user 'sakura' with UID 1001
RUN groupadd -g 1001 sakura && \
    useradd -u 1001 -g sakura -m -s /bin/bash sakura

# Create workspace directory owned by non-root user
WORKDIR /workspace
RUN chown -R sakura:sakura /workspace

# Switch to non-root user
USER 1001:1001

# Set clean environment
ENV HOME=/home/sakura \
    PATH=/home/sakura/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CI=true \
    NONINTERACTIVE=1 \
    NODE_ENV=development

# Entrypoint default shell
CMD ["/bin/bash"]
