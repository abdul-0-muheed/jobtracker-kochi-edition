# ─────────────────────────────────────────────────────────────────────────────
# JobTracker — Dockerfile
# Python 3.11 slim base with Playwright Chromium for scraping.
# Data is persisted via a named volume mounted at /root/.jobtracker
# ─────────────────────────────────────────────────────────────────────────────

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

# Install build essentials needed by some Python packages (lxml, cryptography)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libffi-dev \
        libssl-dev \
        libxml2-dev \
        libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy requirements first to leverage Docker layer cache
COPY requirements.txt .

# Install Python deps into a prefix we can copy into the final image
RUN pip install --upgrade pip \
    && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="JobTracker" \
      description="Local Job Tracker — Flask + SQLite + Playwright" \
      version="1.0"

# Runtime system dependencies (Playwright Chromium needs these)
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 \
        libatk1.0-0 \
        libatk-bridge2.0-0 \
        libcups2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxfixes3 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libpangocairo-1.0-0 \
        libpango-1.0-0 \
        libcairo2 \
        libglib2.0-0 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Set working directory
WORKDIR /app

# Copy application source code
COPY . .

# Install Playwright browsers (Chromium only to keep image small)
RUN playwright install chromium --with-deps 2>/dev/null || playwright install chromium

# ── Environment defaults (override via docker run -e or --env-file) ───────────
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_ENV=production \
    SECRET_KEY=change-me-in-production

# ── Data volume ───────────────────────────────────────────────────────────────
# All persistent data (SQLite DB, sessions, backups, settings) lives here.
VOLUME ["/root/.jobtracker"]

# Expose Flask port
EXPOSE 5000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/')" \
    || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────────
# run.py tries to open a browser which won't work in Docker, so we use flask CLI.
CMD ["python", "-m", "flask", "--app", "app:create_app()", "run", "--host=0.0.0.0", "--port=5000"]
