#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-.venv-linux/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  ./setup.sh
  PYTHON=".venv-linux/bin/python"
fi
exec "$PYTHON" -m unittest discover -s tests -v