#!/usr/bin/env bash
set -euo pipefail

: "${NOTES_DIR:?NOTES_DIR is required}"
: "${PDF_DIR:?PDF_DIR is required}"
: "${FONT_FILE:?FONT_FILE is required}"
: "${FONT_BOLD_FILE:?FONT_BOLD_FILE is required}"
: "${COMBINED_OUTPUT:?COMBINED_OUTPUT is required}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")"

python "$SCRIPT_DIR/scripts/create_combined_pdf.py" \
  --notes-dir "$NOTES_DIR" \
  --output "$COMBINED_OUTPUT" \
  --font-file "$FONT_FILE" \
  --font-bold-file "$FONT_BOLD_FILE"

python "$SCRIPT_DIR/scripts/validate_final_pdf.py" "$COMBINED_OUTPUT" \
  --notes-dir "$NOTES_DIR" \
  --json-output "$(dirname "$COMBINED_OUTPUT")/FINAL_STUDY_NOTES_QA.json"
