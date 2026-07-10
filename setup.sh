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
if [[ "${SKIP_PATCHRIGHT_BROWSER_INSTALL:-0}" != "1" ]]; then
  if command -v google-chrome-stable >/dev/null 2>&1 || command -v google-chrome >/dev/null 2>&1 || command -v chromium-browser >/dev/null 2>&1 || command -v chromium >/dev/null 2>&1; then
    echo "System Chrome/Chromium detected; skipping Patchright browser download."
  else
    "${VENV_DIR}/bin/python" -m patchright install chromium
  fi
fi

echo "Setup complete."
echo "  PDF -> XMind : ./run_pdf_to_xmind.sh"
echo "  MD  -> XMind : ./run_md_to_xmind.sh"
echo "  OPML only    : ./run_opml_to_xmind.sh"
echo "  Login snapshot: ./run_login.sh --profile chrome_profile_login --snapshot-name default"
echo "  Logs         : logs/last_batch_summary.json"