# Campo Crítico — imagen del backend (FastAPI + Uvicorn)
FROM python:3.12-slim AS runtime

# No escribir .pyc y salida sin buffer (logs en vivo).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    CAMPO_DB_PATH=/data/campo_critico.db

WORKDIR /app

# Dependencias primero (mejor cacheo de capas).
COPY requirements.txt ./
RUN pip install --upgrade pip && pip install -r requirements.txt

# Código de la aplicación.
COPY app ./app

# Directorio persistente para la base de datos SQLite (montado como volumen).
RUN mkdir -p /data

# Usuario sin privilegios.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app /data
USER appuser

EXPOSE 8000

# Healthcheck contra el endpoint /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
