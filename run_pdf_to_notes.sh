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

echo "=== PDF/DOCX -> Clean Markdown Notes (via ChatGPT Note Maker) ==="
VENV_DIR=".venv-linux"; PYTHON="${VENV_DIR}/bin/python"
[[ -x "$PYTHON" ]] || ./setup.sh
if ! "$PYTHON" -c "import selenium, pyautogui, pyperclip" 2>/dev/null; then
  "$PYTHON" -m pip install --upgrade pip
  "$PYTHON" -m pip install -r requirements.txt
fi

INPUT_DIR="${INPUT_DIR:-inputs}"
NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PROMPT_FILE="${PROMPT_FILE:-prompts/prompt-rewrite-notes.md}"
DO_PDF="${DO_PDF:-0}"
PDF_DIR="${PDF_DIR:-${NOTES_DIR}/pdfs}"
CREATE_COMBINED="${CREATE_COMBINED:-0}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-${NOTES_DIR}/../COMBINED_NOTES.pdf}"
ENRICH_SOURCE="${ENRICH_SOURCE:-0}"
GENERATE_RICH_INDEX="${GENERATE_RICH_INDEX:-0}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-}"
CSS_FILE="${CSS_FILE:-}"
BOOK_TITLE="${BOOK_TITLE:-Study Notes}"

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

mkdir -p "$NOTES_DIR"
set +e
"$PYTHON" scripts/batch_pdf.py --input-dir "$INPUT_DIR" --output-dir "$NOTES_DIR" --prompt "$PROMPT_FILE" --output-ext md "${BATCH_ARGS[@]}"
EXIT_CODE=$?
set -e

if [[ $EXIT_CODE -eq 0 && "$WANT_PDF" == 1 ]]; then
  mkdir -p "$PDF_DIR"
  if [[ "$ENRICH_SOURCE" == 1 && -n "$ORIGINAL_PARTS_DIR" ]]; then
    "$PYTHON" scripts/enrich_rewritten_notes.py --original-parts "$ORIGINAL_PARTS_DIR" --rewritten-dir "$NOTES_DIR" --inplace
  fi
  if [[ "$GENERATE_RICH_INDEX" == 1 && -n "$ORIGINAL_PARTS_DIR" ]]; then
    "$PYTHON" scripts/generate_study_index.py --parts-dir "$ORIGINAL_PARTS_DIR" --clean-dir "$NOTES_DIR" --output "${NOTES_DIR}/../STUDY_INDEX-rewritten.md" --title "$BOOK_TITLE"
  fi
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
