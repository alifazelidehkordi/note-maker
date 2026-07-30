#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Note Maker: Reference-style A4 Portrait PDF ==="
echo "Project dir: $(pwd)"

VENV_DIR="${VENV_DIR:-.venv-linux}"
PYTHON="${PYTHON:-${VENV_DIR}/bin/python}"
python_available=0
if [[ "$PYTHON" == */* ]]; then
  [[ -x "$PYTHON" ]] && python_available=1
else
  command -v "$PYTHON" >/dev/null 2>&1 && python_available=1
fi
if [[ "$python_available" != "1" ]]; then
  if [[ ! -x ./setup.sh ]]; then
    echo "ERROR: Python environment is missing and setup.sh is unavailable." >&2
    exit 2
  fi
  ./setup.sh
  PYTHON="${VENV_DIR}/bin/python"
fi

NOTES_DIR="${NOTES_DIR:-${INPUT_DIR:-outputs/notes}}"
PDF_DIR="${PDF_DIR:-${OUTPUT_DIR:-${NOTES_DIR}/pdfs}}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-${NOTES_DIR}}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-outputs/notes/FINAL_STUDY_NOTES.pdf}"
QUALITY_REPORT="${QUALITY_REPORT:-${COMBINED_OUTPUT%.pdf}.quality-report.json}"
INDEX_MD="${INDEX_MD:-}"
CSS_FILE="${CSS_FILE:-}"
BOOK_TITLE="${BOOK_TITLE:-}"
CREATE_COMBINED="${CREATE_COMBINED:-1}"
ENRICH_SOURCE="${ENRICH_SOURCE:-0}"
GENERATE_RICH_INDEX="${GENERATE_RICH_INDEX:-0}"

required_vars=(NOTES_DIR PDF_DIR ORIGINAL_PARTS_DIR FONT_FILE FONT_BOLD_FILE)
for name in "${required_vars[@]}"; do
  if [[ -z "${!name:-}" ]]; then
    echo "ERROR: required variable is empty: ${name}" >&2
    exit 2
  fi
done

for dir in "$NOTES_DIR" "$ORIGINAL_PARTS_DIR"; do
  if [[ ! -d "$dir" || ! -r "$dir" ]]; then
    echo "ERROR: directory is missing or unreadable: $dir" >&2
    exit 2
  fi
done

IFS=',:;' read -r -a regular_fonts <<< "$FONT_FILE"
IFS=',:;' read -r -a bold_fonts <<< "$FONT_BOLD_FILE"
for font in "${regular_fonts[@]}" "${bold_fonts[@]}"; do
  [[ -z "$font" ]] && continue
  if [[ ! -f "$font" || ! -r "$font" ]]; then
    echo "ERROR: font is missing or unreadable: $font" >&2
    exit 2
  fi
done

mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")" "$(dirname "$QUALITY_REPORT")"

if ! "$PYTHON" -c "import bs4, fitz, fontTools, mistune, pypdf, weasyprint, yaml" 2>/dev/null; then
  echo "Installing final-PDF dependencies..."
  "$PYTHON" -m pip install beautifulsoup4 fonttools mistune pypdf PyMuPDF PyYAML weasyprint
fi

if [[ "$ENRICH_SOURCE" == "1" ]]; then
  echo "Enriching prepared notes from: $ORIGINAL_PARTS_DIR"
  "$PYTHON" scripts/enrich_rewritten_notes.py \
    --original-parts "$ORIGINAL_PARTS_DIR" \
    --rewritten-dir "$NOTES_DIR" \
    --inplace
fi

if [[ "$GENERATE_RICH_INDEX" == "1" ]]; then
  GENERATED_INDEX="${INDEX_MD:-${NOTES_DIR}/../STUDY_INDEX.generated.md}"
  echo "Generating bilingual Study Index data: $GENERATED_INDEX"
  index_args=(
    scripts/generate_study_index.py
    --notes-dir "$NOTES_DIR"
    --original-parts-dir "$ORIGINAL_PARTS_DIR"
    --output "$GENERATED_INDEX"
  )
  [[ -n "$BOOK_TITLE" ]] && index_args+=(--title "$BOOK_TITLE")
  "$PYTHON" "${index_args[@]}"
  INDEX_MD="$GENERATED_INDEX"
fi

css_args=()
[[ -n "$CSS_FILE" ]] && css_args+=(--css "$CSS_FILE")

if [[ "$CREATE_COMBINED" == "1" ]]; then
  echo "Building final reference-style PDF..."
  args=(
    scripts/create_combined_pdf.py
    --notes-dir "$NOTES_DIR"
    --pdf-dir "$PDF_DIR"
    --original-parts-dir "$ORIGINAL_PARTS_DIR"
    --output "$COMBINED_OUTPUT"
    --report "$QUALITY_REPORT"
  )
  [[ -n "$INDEX_MD" ]] && args+=(--index-md "$INDEX_MD")
  [[ -n "$BOOK_TITLE" ]] && args+=(--title "$BOOK_TITLE")
  args+=("${css_args[@]}")
  "$PYTHON" "${args[@]}"
  echo "PDF and quality report created successfully."
else
  echo "Rendering reference-style session PDFs..."
  args=(
    scripts/convert_md_to_pdf.py
    --batch "$NOTES_DIR"
    --output "$PDF_DIR"
  )
  [[ -n "$BOOK_TITLE" ]] && args+=(--running-title "$BOOK_TITLE")
  args+=("${css_args[@]}")
  "$PYTHON" "${args[@]}"
  echo "Session PDFs created successfully in: $PDF_DIR"
fi
