#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ "${NOTE_MAKER_INHIBIT_SLEEP:-1}" == 1 && "${NOTE_MAKER_INHIBITED:-0}" != 1 ]] \
  && command -v systemd-inhibit >/dev/null 2>&1; then
  if systemd-inhibit --list >/dev/null 2>&1; then
    export NOTE_MAKER_INHIBITED=1
    exec systemd-inhibit \
      --what=sleep:idle \
      --who="Note Maker" \
      --why="Generating study artifacts" \
      --mode=block \
      "$0" "$@"
  fi
  echo "WARNING: systemd sleep inhibitor is unavailable; continuing without it." >&2
fi

echo "=== PDF/DOCX -> OPML -> XMind Pipeline (Linux) ==="
echo "Project dir: $(pwd)"

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  ./setup.sh
fi

if ! "${PYTHON}" -c "import selenium, pyautogui, pyperclip" 2>/dev/null; then
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
fi

CHROME_FOUND=0
for CAND in \
  google-chrome google-chrome-stable chromium chromium-browser \
  /usr/bin/google-chrome /usr/bin/chromium /snap/bin/chromium ; do
  if command -v "$CAND" >/dev/null 2>&1 || [[ -x "$CAND" ]]; then
    CHROME_FOUND=1
    echo "Found browser: $CAND"
    break
  fi
done

if [[ $CHROME_FOUND -eq 0 ]]; then
  echo "ERROR: No Chrome/Chromium found."
  exit 1
fi

INPUT_DIR="${INPUT_DIR:-inputs}"
OPML_DIR="${OPML_DIR:-outputs/opml}"
XMIND_DIR="${XMIND_DIR:-outputs/xmind}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-mind-map.md}"

echo ""
echo "Input dir : ${INPUT_DIR}"
echo "OPML dir  : ${OPML_DIR}  (intermediate)"
echo "XMind dir : ${XMIND_DIR}  (final output)"
echo "Prompt    : ${PROMPT_FILE}"
echo ""

"${PYTHON}" scripts/pipeline.py pdf \
  --input-dir "${INPUT_DIR}" \
  --opml-dir "${OPML_DIR}" \
  --xmind-dir "${XMIND_DIR}" \
  --prompt "${PROMPT_FILE}" \
  "$@"

EXIT_CODE=$?
echo ""
echo "Pipeline finished with exit code: ${EXIT_CODE}"
echo "Final XMind files: ${XMIND_DIR}/"
exit $EXIT_CODE
