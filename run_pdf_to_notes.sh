#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== PDF/DOCX -> Clean Markdown Notes (via ChatGPT Note Maker) ==="
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

echo ""
echo "Input dir : ${INPUT_DIR}"
echo "Notes dir : ${NOTES_DIR}  (final .md files)"
echo "Prompt    : ${PROMPT_FILE}"
if [[ "$DO_PDF" == "1" ]] || [[ " $* " == *" --pdf "* ]]; then
  echo "PDF dir   : ${PDF_DIR}  (will generate PDFs too)"
  if [[ "$CREATE_COMBINED" == "1" ]] || [[ " $* " == *" --combined "* ]]; then
    echo "Combined  : ${COMBINED_OUTPUT}"
  fi
fi
echo ""

mkdir -p "${NOTES_DIR}"

"${PYTHON}" scripts/batch_pdf.py \
  --input-dir "${INPUT_DIR}" \
  --output-dir "${NOTES_DIR}" \
  --prompt "${PROMPT_FILE}" \
  --output-ext md \
  "$@"

EXIT_CODE=$?

if [[ $EXIT_CODE -eq 0 ]] && { [[ "$DO_PDF" == "1" ]] || [[ " $* " == *" --pdf "* ]]; }; then
  mkdir -p "${PDF_DIR}"
  echo ""
  echo "Ensuring PDF dependencies..."
  "${PYTHON}" -c "import weasyprint, markdown" 2>/dev/null || "${PYTHON}" -m pip install weasyprint markdown
  echo "Generating styled PDFs..."
  CSS_ARG=()
  if [[ -n "$CSS_FILE" ]]; then
    CSS_ARG=(--css "$CSS_FILE")
  fi
  "${PYTHON}" scripts/convert_md_to_pdf.py \
    --batch \
    "${NOTES_DIR}" \
    --output "${PDF_DIR}" \
    "${CSS_ARG[@]}"

  if [[ "$CREATE_COMBINED" == "1" ]] || [[ " $* " == *" --combined "* ]]; then
    echo ""
    echo "Creating combined PDF with index page..."
    "${PYTHON}" scripts/create_combined_pdf.py \
      --notes-dir "${NOTES_DIR}" \
      --pdf-dir "${PDF_DIR}" \
      --output "${COMBINED_OUTPUT}"
  fi

  if [[ "$ENRICH_SOURCE" == "1" ]] && [[ -n "$ORIGINAL_PARTS_DIR" ]]; then
    echo ""
    echo "Enriching rewritten notes with original page info..."
    "${PYTHON}" scripts/enrich_rewritten_notes.py \
      --original-parts "$ORIGINAL_PARTS_DIR" \
      --rewritten-dir "${NOTES_DIR}" \
      --inplace
  fi

  if [[ "$GENERATE_RICH_INDEX" == "1" ]] && [[ -n "$ORIGINAL_PARTS_DIR" ]]; then
    echo ""
    echo "Generating rich STUDY_INDEX (فهرست)..."
    RICH_INDEX_OUT="${NOTES_DIR}/../STUDY_INDEX-rewritten.md"
    "${PYTHON}" scripts/generate_study_index.py \
      --parts-dir "$ORIGINAL_PARTS_DIR" \
      --clean-dir "${NOTES_DIR}" \
      --output "$RICH_INDEX_OUT" \
      --title "Rewritten Study Notes"
    echo "Rich index saved to: $RICH_INDEX_OUT"
  fi
fi

echo ""
echo "Done. Exit code: ${EXIT_CODE}"
echo "Your rewritten notes are in: ${NOTES_DIR}/"
if [[ "$DO_PDF" == "1" ]] || [[ " $* " == *" --pdf "* ]]; then
  echo "PDFs are in: ${PDF_DIR}/"
fi
exit $EXIT_CODE
