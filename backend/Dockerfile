# API de SIP-O (FastAPI + Uvicorn), sin root.
FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=America/Mexico_City

# tzdata: la fecha "de hoy" (vacaciones, avisos de los viernes) se calcula con la zona horaria de la empresa
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
# pytest y httpx de pruebas no hacen falta en producción (httpx sí: lo usa la integración con Microsoft)
RUN grep -v '^pytest' requirements.txt > /tmp/requirements-prod.txt \
 && pip install -r /tmp/requirements-prod.txt \
 && rm /tmp/requirements-prod.txt

RUN groupadd --system --gid 10001 sip && useradd --system --uid 10001 --gid sip --home-dir /app --shell /usr/sbin/nologin sip
COPY --chown=root:root app ./app

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# Un solo proceso: las tareas programadas (rotación de turnos, avisos) no deben duplicarse.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
