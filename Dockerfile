FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates texlive-latex-base texlive-latex-extra texlive-lang-cyrillic \
    texlive-xetex texlive-fonts-recommended fonts-dejavu-core fonts-liberation \
    cm-super lmodern \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY run_local.py ./
COPY scripts ./scripts
COPY tests ./tests
RUN useradd --create-home --uid 10001 listok \
    && mkdir -p /app/app/backend/static/generated /app/app/backend/uploads /app/data/jobs \
    && chown -R listok:listok /app
USER listok
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LATEX_TIMEOUT_SECONDS=60
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10000/api/status', timeout=3)"
CMD ["gunicorn", "--chdir", "app/backend", "app:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "60"]
