# POC image for Railway — a scheduled (cron) run of the collection pipeline.
# One `python -m legal_intel` per fire; the container runs to completion and exits.
FROM python:3.12-slim

WORKDIR /app

# Only what the build needs; pdfplumber/anthropic/notion-client ship wheels.
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config

RUN pip install --no-cache-dir ".[poc]"

# config_dir() derives from the package path when pip-installed, which points at
# site-packages — pin it to the copied config explicitly.
ENV LEGAL_INTEL_CONFIG=/app/config \
    PYTHONUNBUFFERED=1 \
    LEGAL_INTEL_NOTION_BACKEND=notion \
    LEGAL_INTEL_LLM_BACKEND=anthropic

# Secrets (NOTION_TOKEN, NOTION_DATABASE_ID, ANTHROPIC_API_KEY,
# NOTION_SOURCE_HEALTH_DB_ID) are injected by Railway as env vars — never baked in.
CMD ["python", "-m", "legal_intel"]
