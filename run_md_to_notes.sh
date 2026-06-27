#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Markdown (## sections) -> Clean Markdown Notes (via ChatGPT Note Maker) ==="
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

MARKDOWN_FILE="${MARKDOWN_FILE:-}"
NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-rewrite-notes.md}"
SECTIONS="${SECTIONS:-}"

if [[ -z "${MARKDOWN_FILE}" ]]; then
  echo "ERROR: Set MARKDOWN_FILE=/path/to/your/notes.md"
  exit 1
fi

echo ""
echo "Markdown file : ${MARKDOWN_FILE}"
echo "Notes dir     : ${NOTES_DIR}"
echo "Prompt        : ${PROMPT_FILE}"
if [[ -n "${SECTIONS}" ]]; then
  echo "Sections      : ${SECTIONS}"
fi
echo ""

mkdir -p "${NOTES_DIR}"

SECTIONS_ARG=()
if [[ -n "${SECTIONS}" ]]; then
  SECTIONS_ARG=(--sections "${SECTIONS}")
fi

"${PYTHON}" scripts/batch_markdown.py \
  --markdown-file "${MARKDOWN_FILE}" \
  --output-dir "${NOTES_DIR}" \
  --prompt "${PROMPT_FILE}" \
  --output-ext md \
  "${SECTIONS_ARG[@]}" \
  "$@"

EXIT_CODE=$?
echo ""
echo "Done. Exit code: ${EXIT_CODE}"
echo "Rewritten notes are in: ${NOTES_DIR}/"
exit $EXIT_CODE
