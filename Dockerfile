FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    MODEL_CACHE_DIR=/opt/model-cache

WORKDIR /app
COPY requirements-runtime.lock ./
RUN python -m pip install --no-cache-dir -r requirements-runtime.lock
RUN python -c "import psycopg; print('PostgreSQL driver ready, libpq', psycopg.pq.version())"

COPY pyproject.toml README.md alembic.ini ./
COPY app ./app
COPY alembic ./alembic
COPY profiles/default.json ./profiles/default.json
COPY examples ./examples
COPY scripts ./scripts
RUN python -m pip install --no-cache-dir --no-deps . \
    && python scripts/cache_model.py \
    && useradd --create-home appuser \
    && mkdir -p /app/data /app/reports \
    && chown -R appuser:appuser /app /opt/model-cache

USER appuser
ENV EMBEDDING_LOCAL_FILES_ONLY=true
CMD ["python", "scripts/scheduled_run.py"]
