#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Share the workspace lockfile, but keep this check's environment self-contained.
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-$PWD/.venv}"
export UV_PYTHON="${UV_PYTHON:-$(cat .python-version)}"
unset VIRTUAL_ENV

uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pytest

# Clear only this library's output so old versions cannot be published by mistake.
uv build --no-sources --clear --out-dir dist
uv run --locked twine check --strict dist/*

# Install each artifact in a fresh environment and ignore the checkout on sys.path.
for artifact in dist/*.whl dist/*.tar.gz; do
    uv run --no-project --isolated --with "$PWD/$artifact" \
        python -I scripts/smoke_install.py pyproject.toml
done
