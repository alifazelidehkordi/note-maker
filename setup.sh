#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

VENV_DIR=".venv-linux"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Creating Python virtual environment in ${VENV_DIR}..."
  python3 -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r requirements.txt

echo "Setup complete."
echo "  PDF -> XMind : ./run_pdf_to_xmind.sh"
echo "  MD  -> XMind : ./run_md_to_xmind.sh"
echo "  OPML only    : ./run_opml_to_xmind.sh"
echo "  Logs         : logs/last_batch_summary.json"