#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR=".venv-linux"; PYTHON="${VENV_DIR}/bin/python"
[[ -x "$PYTHON" ]] || ./setup.sh
if ! "$PYTHON" -c "import selenium, pyautogui, pyperclip" 2>/dev/null; then
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
fi

MARKDOWN_FILE="${MARKDOWN_FILE:-}"
NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-rewrite-notes.md}"
SECTIONS="${SECTIONS:-}"
DO_PDF="${DO_PDF:-0}"
PDF_DIR="${PDF_DIR:-${NOTES_DIR}/pdfs}"
CREATE_COMBINED="${CREATE_COMBINED:-0}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-${NOTES_DIR}/../COMBINED_NOTES.pdf}"
BOOK_TITLE="${BOOK_TITLE:-Study Notes}"
CSS_FILE="${CSS_FILE:-}"
[[ -n "$MARKDOWN_FILE" ]] || { echo "ERROR: Set MARKDOWN_FILE=/path/to/your/notes.md"; exit 1; }

BATCH_ARGS=(); CLI_PDF=0; CLI_COMBINED=0
for arg in "$@"; do
  case "$arg" in
    --pdf) CLI_PDF=1 ;;
    --combined) CLI_COMBINED=1 ;;
    *) BATCH_ARGS+=("$arg") ;;
  esac
done
WANT_COMBINED=0; [[ "$CREATE_COMBINED" == 1 || "$CLI_COMBINED" == 1 ]] && WANT_COMBINED=1
WANT_PDF=0; [[ "$DO_PDF" == 1 || "$CLI_PDF" == 1 || "$WANT_COMBINED" == 1 ]] && WANT_PDF=1
SECTIONS_ARG=(); [[ -n "$SECTIONS" ]] && SECTIONS_ARG=(--sections "$SECTIONS")

mkdir -p "$NOTES_DIR"
set +e
"$PYTHON" scripts/batch_markdown.py --markdown-file "$MARKDOWN_FILE" --output-dir "$NOTES_DIR" --prompt "$PROMPT_FILE" --output-ext md "${SECTIONS_ARG[@]}" "${BATCH_ARGS[@]}"
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 0 && "$WANT_PDF" == 1 ]]; then
  mkdir -p "$PDF_DIR"
  "$PYTHON" -c "import weasyprint, markdown, pypdf" 2>/dev/null || "$PYTHON" -m pip install weasyprint markdown pypdf
  CSS_ARG=(); [[ -n "$CSS_FILE" ]] && CSS_ARG=(--css "$CSS_FILE")
  "$PYTHON" scripts/convert_md_to_pdf.py --batch "$NOTES_DIR" --output "$PDF_DIR" "${CSS_ARG[@]}"
  if [[ "$WANT_COMBINED" == 1 ]]; then
    INDEX_MD="${INDEX_MD:-${NOTES_DIR}/../STUDY_INDEX-rewritten.md}"
    INDEX_ARG=(); [[ -f "$INDEX_MD" ]] && INDEX_ARG=(--index-md "$INDEX_MD")
    "$PYTHON" scripts/create_combined_pdf.py --notes-dir "$NOTES_DIR" --pdf-dir "$PDF_DIR" --output "$COMBINED_OUTPUT" --title "$BOOK_TITLE" "${CSS_ARG[@]}" "${INDEX_ARG[@]}"
  fi
fi

echo "Done. Exit code: $EXIT_CODE"
exit "$EXIT_CODE"
