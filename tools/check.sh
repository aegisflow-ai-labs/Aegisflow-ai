#!/usr/bin/env sh
set -eu
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
.venv/bin/ruff check src tests tools
.venv/bin/ruff format --check src tests tools
.venv/bin/mypy src
.venv/bin/pytest -q
