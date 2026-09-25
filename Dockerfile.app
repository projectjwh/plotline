# Plotline app backend (src/app): accounts, fanboards, feed, media, claims, premium.
# Reads the pre-built analytics warehouse (downloaded on boot from PLOTLINE_WAREHOUSE_URL)
# and keeps app state in Postgres. Build:  docker build -f Dockerfile.app -t plotline-app .
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-app.txt .
RUN pip install -r requirements-app.txt

# only what the app imports: src/app, the two shared model helpers, policy, migrations
COPY src/app ./src/app
COPY src/models/earnings.py src/models/genre_map.py ./src/models/
COPY config/policy ./config/policy
COPY alembic.ini ./
COPY migrations ./migrations

RUN useradd --create-home --uid 10001 plotline && mkdir -p /app/data && chown plotline /app/data
USER plotline

ENV PLOTLINE_ENV=prod PORT=8000 PLOTLINE_WAREHOUSE_PATH=/app/data/plotline.duckdb PLOTLINE_TRUST_PROXY=true
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready',timeout=3).status==200 else 1)"
CMD ["sh", "-c", "uvicorn --factory src.app.main:create_app --host 0.0.0.0 --port ${PORT:-8000} --no-proxy-headers"]
# client IPs: the app takes the rightmost X-Forwarded-For hop itself (or PLOTLINE_CLIENT_IP_HEADER); uvicorn must not rewrite them
