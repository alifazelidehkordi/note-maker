#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== PDF/DOCX -> Clean Markdown Notes (via ChatGPT Note Maker) ==="
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

INPUT_DIR="${INPUT_DIR:-inputs}"
NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-rewrite-notes.md}"

echo ""
echo "Input dir : ${INPUT_DIR}"
echo "Notes dir : ${NOTES_DIR}  (final .md files)"
echo "Prompt    : ${PROMPT_FILE}"
echo ""

mkdir -p "${NOTES_DIR}"

"${PYTHON}" scripts/batch_pdf.py \
  --input-dir "${INPUT_DIR}" \
  --output-dir "${NOTES_DIR}" \
  --prompt "${PROMPT_FILE}" \
  --output-ext md \
  "$@"

EXIT_CODE=$?
echo ""
echo "Done. Exit code: ${EXIT_CODE}"
echo "Your rewritten notes are in: ${NOTES_DIR}/"
exit $EXIT_CODE
