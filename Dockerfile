FROM python:3.11-slim

WORKDIR /app

# System deps for XGBoost and scikit-learn
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (no torch needed for serving — only XGBoost/sklearn)
COPY requirements-serve.txt .
RUN pip install --no-cache-dir -r requirements-serve.txt

# Copy application code
COPY data/ data/
COPY features/ features/
COPY models/ models/
COPY webapp/ webapp/
COPY scripts/load_db.py scripts/load_db.py

# Restore SQLite database from snapshot (if present)
RUN if [ -f data/db_snapshot.sql.gz ]; then \
      python scripts/load_db.py --force && \
      rm -f data/db_snapshot.sql.gz; \
    fi

ENV FLASK_ENV=production
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "120", "webapp.app:app"]
