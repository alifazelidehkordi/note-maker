#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Markdown -> OPML -> XMind Pipeline (Linux) ==="
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
OPML_DIR="${OPML_DIR:-outputs/opml}"
XMIND_DIR="${XMIND_DIR:-outputs/xmind}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-mind-map.md}"

if [[ -z "${MARKDOWN_FILE}" ]]; then
  echo "ERROR: Set MARKDOWN_FILE to your source .md file."
  echo "Example:"
  echo "  MARKDOWN_FILE=/path/to/notes.md ./run_md_to_xmind.sh --overwrite"
  exit 1
fi

echo ""
echo "Markdown file: ${MARKDOWN_FILE}"
echo "OPML dir     : ${OPML_DIR}  (intermediate)"
echo "XMind dir    : ${XMIND_DIR}  (final output)"
echo "Prompt       : ${PROMPT_FILE}"
echo ""

"${PYTHON}" scripts/pipeline.py markdown \
  --markdown-file "${MARKDOWN_FILE}" \
  --opml-dir "${OPML_DIR}" \
  --xmind-dir "${XMIND_DIR}" \
  --prompt "${PROMPT_FILE}" \
  "$@"

EXIT_CODE=$?
echo ""
echo "Pipeline finished with exit code: ${EXIT_CODE}"
echo "Final XMind files: ${XMIND_DIR}/"
exit $EXIT_CODE