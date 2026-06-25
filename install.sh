#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
VENV_DIR="${VENV_DIR:-$HOME/venv/$PROJECT_NAME}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
UV_BIN="${UV_BIN:-uv}"

if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  echo "uv is required. Install it first: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

mkdir -p "$(dirname "$VENV_DIR")"
"$UV_BIN" venv --allow-existing --python "$PYTHON_BIN" "$VENV_DIR"
"$UV_BIN" pip install --python "$VENV_DIR/bin/python" --upgrade "$PROJECT_DIR"

if [ ! -f "$PROJECT_DIR/.env" ] && [ -f "$PROJECT_DIR/.env.example" ]; then
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
fi

cat <<MSG
Installed/updated $PROJECT_NAME
venv: $VENV_DIR
run:  source $PROJECT_DIR/run.sh 0.0.0.0 8000
MSG
