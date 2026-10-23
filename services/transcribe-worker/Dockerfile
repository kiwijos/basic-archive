FROM python:3.12.7-slim-bookworm AS build
RUN pip install --no-cache-dir uv==0.10.4
WORKDIR /app
COPY services/transcribe-worker/pyproject.toml services/transcribe-worker/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/transcribe-worker/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.7-slim-bookworm
# Tesseract with English and Swedish language data, from Debian so it follows the base image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-swe \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app/.venv /app/.venv
COPY contracts /app/contracts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CONTRACTS_DIR=/app/contracts
USER 10001
EXPOSE 8080
CMD ["python", "-m", "transcribe_worker.main"]
