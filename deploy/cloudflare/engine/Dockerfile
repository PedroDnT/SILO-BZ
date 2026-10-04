# The portfolio-diagnosis engine behind a small HTTP server (map #510, slice E step 1).
# Build from the repository root:
#   docker build -f deploy/cloudflare/engine/Dockerfile -t silo-engine .
# Dockerfile.dockerignore (next to this file) whitelists src/portfolio only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

# WeasyPrint needs pango and harfbuzz-subset (its Debian install list); report.css asks for DejaVu Sans.
# poppler-utils gives pdftotext, the BTG statement reader's first extractor (pypdf is the fallback).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY deploy/cloudflare/engine/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt && rm /tmp/requirements.txt

COPY src/__init__.py src/__init__.py
COPY src/portfolio src/portfolio
COPY deploy/cloudflare/engine/start.sh /app/start.sh

# Fails the build if the renderer cannot load its native libraries.
RUN python -c "from weasyprint import HTML; HTML(string='<p>ação</p>').write_pdf()" \
    && useradd --system --uid 10001 --create-home --home-dir /home/engine --shell /usr/sbin/nologin engine

USER engine
EXPOSE 8080
# start.sh: gunicorn, 1 worker x 4 threads, 600 s timeout; trusts the Cloudflare egress CA when asked.
CMD ["sh", "/app/start.sh"]
