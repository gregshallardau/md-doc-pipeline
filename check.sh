#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

source .venv/bin/activate 2>/dev/null || {
  echo "No .venv found — run init.sh first"
  exit 1
}

echo "==> ruff"
ruff check .

echo "==> black"
black --check .

echo "==> mypy (informational — not a hard gate yet)"
mypy md_doc/ || true

echo "==> pytest"
pytest tests/ -v --tb=short

echo ""
echo "All checks passed."
