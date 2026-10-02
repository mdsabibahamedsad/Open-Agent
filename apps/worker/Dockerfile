FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY src ./src
RUN chown -R appuser:appuser /app

USER appuser

# Default: cloud fleet worker (SIGTERM → graceful drain). Override with
# `python -m worker.main` (legacy) or `python -m worker.cloud_scheduler`.
CMD ["python", "-m", "worker.cloud_worker"]