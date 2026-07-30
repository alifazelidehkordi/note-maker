#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PDF_DIR="${PDF_DIR:-${NOTES_DIR}/pdfs}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-${NOTES_DIR}}"
FONT_FILE="${FONT_FILE:?FONT_FILE is required}"
FONT_BOLD_FILE="${FONT_BOLD_FILE:?FONT_BOLD_FILE is required}"
LATIN_REGULAR_FILE="${LATIN_REGULAR_FILE:-${FONT_FILE}}"
LATIN_BOLD_FILE="${LATIN_BOLD_FILE:-${FONT_BOLD_FILE}}"
ARABIC_REGULAR_FILE="${ARABIC_REGULAR_FILE:-${FONT_FILE}}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-outputs/notes/FINAL_STUDY_NOTES.pdf}"
INDEX_MD="${INDEX_MD:-}"
BOOK_TITLE="${BOOK_TITLE:-}"
QC_REPORT="${QC_REPORT:-${COMBINED_OUTPUT%.pdf}.qc.txt}"
DEBUG_HTML="${DEBUG_HTML:-}"
PYTHON="${PYTHON:-python3}"

for path in \
  "$NOTES_DIR" \
  "$FONT_FILE" \
  "$FONT_BOLD_FILE" \
  "$LATIN_REGULAR_FILE" \
  "$LATIN_BOLD_FILE" \
  "$ARABIC_REGULAR_FILE"
do
  [[ -r "$path" ]] || { echo "Required input is missing or unreadable: $path" >&2; exit 2; }
done
mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")" "$(dirname "$QC_REPORT")"

ARGS=(
  --notes-dir "$NOTES_DIR"
  --pdf-dir "$PDF_DIR"
  --output "$COMBINED_OUTPUT"
  --font-file "$FONT_FILE"
  --font-bold-file "$FONT_BOLD_FILE"
  --latin-regular-file "$LATIN_REGULAR_FILE"
  --latin-bold-file "$LATIN_BOLD_FILE"
  --arabic-regular-file "$ARABIC_REGULAR_FILE"
  --qc-report "$QC_REPORT"
)
[[ -n "$INDEX_MD" ]] && ARGS+=(--index-md "$INDEX_MD")
[[ -n "$BOOK_TITLE" ]] && ARGS+=(--title "$BOOK_TITLE")
[[ -n "$DEBUG_HTML" ]] && ARGS+=(--debug-html "$DEBUG_HTML")

"$PYTHON" scripts/create_combined_pdf.py "${ARGS[@]}"
