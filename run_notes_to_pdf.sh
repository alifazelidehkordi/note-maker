#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Note Maker: Markdown → Styled PDF ==="
echo "Project dir: $(pwd)"

VENV_DIR=".venv-linux"
PYTHON="${VENV_DIR}/bin/python"

if [[ ! -x "${PYTHON}" ]]; then
  ./setup.sh
fi

NOTES_DIR="${NOTES_DIR:-${INPUT_DIR:-outputs/notes}}"
PDF_DIR="${PDF_DIR:-${OUTPUT_DIR:-${NOTES_DIR}/pdfs}}"
CREATE_COMBINED="${CREATE_COMBINED:-0}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-${NOTES_DIR}/../COMBINED_NOTES.pdf}"
ENRICH_SOURCE="${ENRICH_SOURCE:-0}"
GENERATE_RICH_INDEX="${GENERATE_RICH_INDEX:-0}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-}"
INDEX_MD="${INDEX_MD:-${NOTES_DIR}/../STUDY_INDEX-rewritten.md}"
CSS_FILE="${CSS_FILE:-}"

echo ""
echo "Notes dir : ${NOTES_DIR}"
echo "PDF dir   : ${PDF_DIR}"
if [[ -n "$CSS_FILE" ]]; then
  echo "Extra CSS : ${CSS_FILE}"
fi
if [[ "$CREATE_COMBINED" == "1" ]]; then
  echo "Combined  : ${COMBINED_OUTPUT}"
fi
echo ""

"${PYTHON}" -c "import weasyprint, markdown, pypdf" 2>/dev/null || "${PYTHON}" -m pip install weasyprint markdown pypdf

if [[ "$ENRICH_SOURCE" == "1" ]] && [[ -n "$ORIGINAL_PARTS_DIR" ]]; then
  echo "Enriching notes from: ${ORIGINAL_PARTS_DIR}"
  "${PYTHON}" scripts/enrich_rewritten_notes.py \
    --original-parts "$ORIGINAL_PARTS_DIR" \
    --rewritten-dir "${NOTES_DIR}" \
    --inplace
fi

if [[ "$GENERATE_RICH_INDEX" == "1" ]] && [[ -n "$ORIGINAL_PARTS_DIR" ]]; then
  echo "Generating rich STUDY_INDEX..."
  "${PYTHON}" scripts/generate_study_index.py \
    --parts-dir "$ORIGINAL_PARTS_DIR" \
    --clean-dir "${NOTES_DIR}" \
    --output "$INDEX_MD" \
    --title "Rewritten Study Notes"
fi

mkdir -p "${PDF_DIR}"

CSS_ARG=()
if [[ -n "$CSS_FILE" ]]; then
  CSS_ARG=(--css "$CSS_FILE")
fi

echo "Converting topic notes to PDF..."
"${PYTHON}" scripts/convert_md_to_pdf.py \
  --batch \
  "${NOTES_DIR}" \
  --output "${PDF_DIR}" \
  "${CSS_ARG[@]}"

if [[ "$CREATE_COMBINED" == "1" ]]; then
  echo ""
  echo "Building combined PDF..."
  INDEX_ARG=()
  if [[ -f "$INDEX_MD" ]]; then
    INDEX_ARG=(--index-md "$INDEX_MD")
  fi
  "${PYTHON}" scripts/create_combined_pdf.py \
    --notes-dir "${NOTES_DIR}" \
    --pdf-dir "${PDF_DIR}" \
    --output "${COMBINED_OUTPUT}" \
    "${INDEX_ARG[@]}"
fi

echo ""
echo "✅ PDFs in: ${PDF_DIR}/"
ls -lh "${PDF_DIR}/" | head -12