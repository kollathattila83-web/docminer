FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml ./
COPY docminer ./docminer
RUN pip install --no-cache-dir .

COPY config ./config
ENV DOCMINER_CONFIG_DIR=/app/config DOCMINER_DATA_DIR=/data

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app

EXPOSE 8000
CMD ["uvicorn", "docminer.api:app", "--host", "0.0.0.0", "--port", "8000"]
