FROM python:3.14-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* && apt-get dist-clean

RUN curl -Ls https://astral.sh/uv/install.sh | sh
ENV PATH="/app/.venv/bin:/root/.local/bin:${PATH}"

COPY pyproject.toml uv.lock /app/
COPY README.md ./

# Copy Workspace Dependency
COPY /api/pyproject.toml ./api/
COPY /api/README.md ./api/
COPY /libs/config/pyproject.toml ./libs/config/
COPY /libs/config/README.md ./libs/config/

RUN uv sync --frozen --no-dev --no-install-project --package api

COPY /api/src /app/api/src
COPY /libs/config ./libs/config

RUN uv sync --frozen --no-dev --compile-bytecode  --package api

EXPOSE 8000

ENV PATH="/app/.venv/bin:$PATH"
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
