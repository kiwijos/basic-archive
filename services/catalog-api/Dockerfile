FROM python:3.12.7-slim-bookworm AS build
RUN pip install --no-cache-dir uv==0.10.4
WORKDIR /app
COPY services/catalog-api/pyproject.toml services/catalog-api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/catalog-api/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.7-slim-bookworm
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app/.venv /app/.venv
COPY contracts /app/contracts
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 CONTRACTS_DIR=/app/contracts
USER 10001
EXPOSE 8000
CMD ["python", "-m", "catalog_api.main"]
