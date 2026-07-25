# Plotline API — lean read-only image serving the DuckDB warehouse.
# The heavy pipeline (scrape/enrich/build) runs OFFLINE (run_pipeline.py + CI);
# this container only serves a pre-built plotline.duckdb, which it either reads
# from a mounted volume (local) or downloads on boot from PLOTLINE_WAREHOUSE_URL
# (prod). No Playwright / torch / ML deps here — keeps the image small + fast.
FROM python:3.12-slim
WORKDIR /app

# Slim runtime deps only. psycopg/stripe are imported lazily and only needed
# once DATABASE_URL / STRIPE_* are set, but baking them keeps prod one-command.
RUN pip install --no-cache-dir \
    "fastapi>=0.110" "uvicorn[standard]>=0.27" "duckdb>=0.9" \
    "slowapi>=0.1.9" "psycopg[binary]>=3.1" "stripe>=8.0"

COPY src/api ./src/api

ENV PLOTLINE_ENV=prod PORT=8000
EXPOSE 8000

# Readiness = warehouse is queryable (not just process-up).
HEALTHCHECK --interval=30s --timeout=4s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready',timeout=3).status==200 else 1)"

CMD ["sh", "-c", "uvicorn src.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
