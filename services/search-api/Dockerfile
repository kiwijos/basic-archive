FROM python:3.12.15-slim-trixie AS build
RUN pip install --no-cache-dir uv==0.10.4
WORKDIR /app
COPY services/search-api/pyproject.toml services/search-api/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/search-api/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12.15-slim-trixie
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
CMD ["python", "-m", "search_api.main"]
