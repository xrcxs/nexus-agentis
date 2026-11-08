FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY eval /app/eval

ENV PYTHONPATH=/app
ENV NEXUS_DB_PATH=/data/nexus_agentis.db
ENV NEXUS_CHECKPOINT_DB_PATH=/data/nexus_checkpoints.db

VOLUME ["/data"]
EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
