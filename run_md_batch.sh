#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== ChatGPT Mind Map — Markdown Sections Batch (Linux) ==="
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
OUTPUT_DIR="${OUTPUT_DIR:-outputs/markdown}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-mind-map.md}"

if [[ -z "${MARKDOWN_FILE}" ]]; then
  echo "ERROR: Set MARKDOWN_FILE to your source .md file."
  echo "Example:"
  echo "  MARKDOWN_FILE=/path/to/notes.md ./run_md_batch.sh --overwrite"
  exit 1
fi

echo ""
echo "Markdown file: ${MARKDOWN_FILE}"
echo "Output dir   : ${OUTPUT_DIR}"
echo "Prompt       : ${PROMPT_FILE}"
echo ""

ARGS=(
  --markdown-file "${MARKDOWN_FILE}"
  --output-dir "${OUTPUT_DIR}"
  --prompt "${PROMPT_FILE}"
)

"${PYTHON}" scripts/batch_markdown.py "${ARGS[@]}" "$@"

EXIT_CODE=$?
echo "Batch finished with exit code: ${EXIT_CODE}"
echo "Results: ${OUTPUT_DIR}/"
exit $EXIT_CODE