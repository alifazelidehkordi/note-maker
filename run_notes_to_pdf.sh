#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-.venv-linux}"
PYTHON="${PYTHON:-${VENV_DIR}/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  ./setup.sh
fi

: "${NOTES_DIR:?NOTES_DIR is required}"
: "${PDF_DIR:?PDF_DIR is required}"
: "${FONT_FILE:?FONT_FILE is required}"
: "${FONT_BOLD_FILE:?FONT_BOLD_FILE is required}"
: "${COMBINED_OUTPUT:?COMBINED_OUTPUT is required}"

mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")"

"$PYTHON" -c "import bs4, fitz, mistune, pypdf, weasyprint, yaml" >/dev/null

"$PYTHON" scripts/create_combined_pdf.py \
  --notes-dir "$NOTES_DIR" \
  --output "$COMBINED_OUTPUT" \
  --font-file "$FONT_FILE" \
  --font-bold-file "$FONT_BOLD_FILE"

"$PYTHON" scripts/validate_final_pdf.py "$COMBINED_OUTPUT" \
  --notes-dir "$NOTES_DIR" \
  --json-output "$(dirname "$COMBINED_OUTPUT")/FINAL_STUDY_NOTES_QA.json"
