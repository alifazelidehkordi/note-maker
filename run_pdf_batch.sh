#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== ChatGPT Mind Map — PDF/DOCX Batch (Linux) ==="
echo "Project dir: $(pwd)"

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  echo "Python venv not found. Running setup.sh..."
  ./setup.sh
fi

if ! "${PYTHON}" -c "import selenium, pyautogui, pyperclip" 2>/dev/null; then
  echo "Dependencies missing. Reinstalling..."
  "${PYTHON}" -m pip install --upgrade pip
  "${PYTHON}" -m pip install -r requirements.txt
fi

CHROME_FOUND=0
for CAND in \
  google-chrome google-chrome-stable chromium chromium-browser \
  /usr/bin/google-chrome /usr/bin/google-chrome-stable \
  /usr/bin/chromium /usr/bin/chromium-browser \
  /snap/bin/chromium /snap/bin/chromium-browser \
  /opt/google/chrome/chrome ; do
  if command -v "$CAND" >/dev/null 2>&1 || [[ -x "$CAND" ]]; then
    CHROME_FOUND=1
    echo "Found browser: $CAND"
    break
  fi
done

if [[ $CHROME_FOUND -eq 0 ]]; then
  echo "ERROR: No Chrome/Chromium found. Install google-chrome-stable or chromium-browser."
  exit 1
fi

INPUT_DIR="${INPUT_DIR:-inputs}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-mind-map.md}"

echo ""
echo "Input dir : ${INPUT_DIR}"
echo "Output dir: ${OUTPUT_DIR}"
echo "Prompt    : ${PROMPT_FILE}"
echo ""

"${PYTHON}" scripts/batch_pdf.py \
  --input-dir "${INPUT_DIR}" \
  --output-dir "${OUTPUT_DIR}" \
  --prompt "${PROMPT_FILE}" \
  "$@"

EXIT_CODE=$?
echo "Batch finished with exit code: ${EXIT_CODE}"
echo "Results: ${OUTPUT_DIR}/"
exit $EXIT_CODE