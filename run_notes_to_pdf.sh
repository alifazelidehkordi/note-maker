#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Note Maker: prepared Markdown -> final verified PDF ==="

VENV_DIR="${VENV_DIR:-.venv-linux}"
PYTHON="${PYTHON:-${VENV_DIR}/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  ./setup.sh
fi

NOTES_DIR="${NOTES_DIR:-${INPUT_DIR:-outputs/notes}}"
PDF_DIR="${PDF_DIR:-${OUTPUT_DIR:-${NOTES_DIR}/pdfs}}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-}"
SOURCE_INDEX="${SOURCE_INDEX:-}"
if [[ -z "$SOURCE_INDEX" ]]; then
  if [[ -n "$ORIGINAL_PARTS_DIR" && -f "$ORIGINAL_PARTS_DIR/INDEX.md" ]]; then
    SOURCE_INDEX="$ORIGINAL_PARTS_DIR/INDEX.md"
  else
    SOURCE_INDEX="$NOTES_DIR/INDEX.md"
  fi
fi
INDEX_MD="${INDEX_MD:-${NOTES_DIR}/STUDY_INDEX-rewritten.md}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-${NOTES_DIR}/FINAL_STUDY_NOTES.pdf}"
CSS_FILE="${CSS_FILE:-}"
BOOK_TITLE="${BOOK_TITLE:-}"

for directory in "$NOTES_DIR"; do
  [[ -d "$directory" && -r "$directory" ]] || { echo "Required directory is missing or unreadable: $directory" >&2; exit 2; }
done
[[ -f "$SOURCE_INDEX" && -r "$SOURCE_INDEX" ]] || { echo "Primary INDEX is missing or unreadable: $SOURCE_INDEX" >&2; exit 2; }
[[ -n "${FONT_FILE:-}" && -f "$FONT_FILE" && -r "$FONT_FILE" ]] || { echo "FONT_FILE is missing or unreadable" >&2; exit 2; }
[[ -n "${FONT_BOLD_FILE:-}" && -f "$FONT_BOLD_FILE" && -r "$FONT_BOLD_FILE" ]] || { echo "FONT_BOLD_FILE is missing or unreadable" >&2; exit 2; }

"$PYTHON" -c "import weasyprint, markdown, pypdf, yaml" 2>/dev/null || "$PYTHON" -m pip install weasyprint markdown pypdf pyyaml

mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")"

CSS_ARG=()
[[ -n "$CSS_FILE" ]] && CSS_ARG=(--css "$CSS_FILE")
TITLE_ARG=()
[[ -n "$BOOK_TITLE" ]] && TITLE_ARG=(--title "$BOOK_TITLE")

echo "Notes dir       : $NOTES_DIR"
echo "Source INDEX    : $SOURCE_INDEX"
echo "Rich index      : $INDEX_MD"
echo "Topic PDF dir   : $PDF_DIR"
echo "Final PDF       : $COMBINED_OUTPUT"

echo "Generating bilingual Study Index from the prepared source INDEX..."
"$PYTHON" scripts/generate_study_index.py \
  --index "$SOURCE_INDEX" \
  --notes-dir "$NOTES_DIR" \
  --output "$INDEX_MD"

echo "Converting numbered topic notes to A4 portrait PDFs..."
"$PYTHON" scripts/convert_md_to_pdf.py \
  --batch "$NOTES_DIR" \
  --output "$PDF_DIR" \
  --no-page-numbers \
  "${CSS_ARG[@]}"

echo "Building and verifying the final combined PDF..."
"$PYTHON" scripts/create_combined_pdf.py \
  --notes-dir "$NOTES_DIR" \
  --pdf-dir "$PDF_DIR" \
  --source-index "$SOURCE_INDEX" \
  --index-md "$INDEX_MD" \
  --output "$COMBINED_OUTPUT" \
  "${TITLE_ARG[@]}" \
  "${CSS_ARG[@]}"

echo "Final verified PDF: $COMBINED_OUTPUT"
