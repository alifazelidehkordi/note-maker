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

# Make sure deps are present
"${PYTHON}" -c "import weasyprint, markdown" 2>/dev/null || "${PYTHON}" -m pip install weasyprint markdown

INPUT_DIR="${INPUT_DIR:-outputs/notes}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/pdfs}"
CSS_FILE="${CSS_FILE:-}"

echo ""
echo "Input dir  : ${INPUT_DIR}"
echo "Output dir : ${OUTPUT_DIR}"
if [[ -n "$CSS_FILE" ]]; then
  echo "Extra CSS  : ${CSS_FILE}"
fi
echo ""

mkdir -p "${OUTPUT_DIR}"

CSS_ARG=()
if [[ -n "$CSS_FILE" ]]; then
  CSS_ARG=(--css "$CSS_FILE")
fi

"${PYTHON}" scripts/convert_md_to_pdf.py \
  --batch \
  "${INPUT_DIR}" \
  --output "${OUTPUT_DIR}" \
  "${CSS_ARG[@]}"

echo ""
echo "✅ PDFs created in: ${OUTPUT_DIR}/"
ls -lh "${OUTPUT_DIR}/" | head -10
