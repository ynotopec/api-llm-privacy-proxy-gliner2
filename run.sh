#!/usr/bin/env bash
# Source/direct-compatible runner:
#   ./run.sh [IP] [PORT]
#   source ./run.sh [IP] [PORT]
# systemd example:
#   ExecStart=/bin/bash -lc 'source /opt/api-llm-privacy-proxy-gliner2/run.sh 0.0.0.0 8000'

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"
VENV_DIR="${VENV_DIR:-$HOME/venv/$PROJECT_NAME}"
HOST="${1:-${HOST:-127.0.0.1}}"
PORT="${2:-${PORT:-8000}}"
AUTO_INSTALL="${AUTO_INSTALL:-1}"

if [ -f "$PROJECT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$PROJECT_DIR/.env"
  set +a
fi

if [ ! -x "$VENV_DIR/bin/activate" ]; then
  if [ "$AUTO_INSTALL" = "1" ]; then
    echo "Missing venv: $VENV_DIR. Running install.sh first..." >&2
    VENV_DIR="$VENV_DIR" "$PROJECT_DIR/install.sh"
  else
    echo "Missing venv: $VENV_DIR. Run ./install.sh first, or set AUTO_INSTALL=1." >&2
    return 1 2>/dev/null || exit 1
  fi
fi

# Safe defaults for NVIDIA H100 / DGX Spark style CUDA hosts. Override in .env if needed.
export CUDA_DEVICE_ORDER="${CUDA_DEVICE_ORDER:-PCI_BUS_ID}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

cd "$PROJECT_DIR"
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m uvicorn app.main:app --host "$HOST" --port "$PORT"
