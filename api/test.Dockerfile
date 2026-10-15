FROM python:3.14-slim-trixie

ENV PYTHONUNBUFFERED=1

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Compile bytecode
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#compiling-bytecode
ENV UV_COMPILE_BYTECODE=1

# uv Cache
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#caching
ENV UV_LINK_MODE=copy

WORKDIR /app/

# Place executables in the environment at the front of the path
# Ref: https://docs.astral.sh/uv/guides/integration/docker/#using-the-environment
ENV PATH="/app/.venv/bin:$PATH"


COPY src/ src/
COPY pyproject.toml .
COPY uv.lock .
COPY README.md .


RUN uv sync --frozen  --no-dev --compile-bytecode

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0","--port", "8000"]
