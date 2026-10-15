FROM python:3.14-slim-trixie AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /build

COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

# Export only the API's dependencies from the workspace lockfile. The other
# member's metadata is required for workspace discovery, not for installation.
COPY pyproject.toml uv.lock ./
COPY api/pyproject.toml ./api/pyproject.toml
COPY python-extension-with-rust/pyproject.toml ./python-extension-with-rust/pyproject.toml

RUN uv export --frozen --package api --no-dev --no-emit-workspace \
    > /tmp/requirements.txt

RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /app/.venv \
    && uv pip install --no-config --no-deps --python /app/.venv/bin/python --require-hashes \
        --requirements /tmp/requirements.txt

WORKDIR /app

COPY api/pyproject.toml api/README.md ./
COPY api/src ./src
COPY api/alembic.ini ./alembic.ini
COPY api/alembic ./alembic
COPY api/docker-entrypoint.sh ./docker-entrypoint.sh

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --no-config --python /app/.venv/bin/python --no-deps --compile-bytecode .

FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    RUN_MIGRATIONS=true

WORKDIR /app

COPY --from=builder /app /app

RUN chmod 755 /app/docker-entrypoint.sh \
    && useradd --system --uid 10001 --no-create-home api \
    && mkdir -p /app/data /app/temp \
    && chown api:api /app/data /app/temp

USER api

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
