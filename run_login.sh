#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Python venv not found. Running setup.sh..."
  ./setup.sh
fi

exec "${PYTHON}" scripts/profile_bootstrap.py login "$@"
