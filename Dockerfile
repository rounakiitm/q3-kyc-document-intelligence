FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo \
    zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py ./
COPY frontend ./frontend
COPY samples ./samples

ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SAMPLE_INPUT_DIR=/app/samples

EXPOSE 8080

CMD ["sh", "-c", "uvicorn service:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-keep-alive 3600"]
