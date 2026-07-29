#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=== Note Maker: final Study Notes PDF ==="

VENV_DIR="${VENV_DIR:-.venv-linux}"
if [[ -x "${VENV_DIR}/bin/python" ]]; then
  PYTHON="${VENV_DIR}/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PDF_DIR="${PDF_DIR:-${NOTES_DIR}/pdfs}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-${NOTES_DIR}}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-outputs/notes/FINAL_STUDY_NOTES.pdf}"
GENERATED_INDEX="${GENERATED_INDEX:-${PDF_DIR}/STUDY_INDEX.md}"
REPORT_JSON="${REPORT_JSON:-${COMBINED_OUTPUT%.pdf}.report.json}"
CSS_FILE="${CSS_FILE:-}"
BOOK_TITLE="${BOOK_TITLE:-}"
PAGE_NUMBER_START="${PAGE_NUMBER_START:-1}"
SOURCE_INDEX="${SOURCE_INDEX:-}"

if [[ -z "${SOURCE_INDEX}" ]]; then
  for candidate in "${ORIGINAL_PARTS_DIR}/INDEX.md" "${NOTES_DIR}/INDEX.md"; do
    if [[ -f "${candidate}" ]]; then
      SOURCE_INDEX="${candidate}"
      break
    fi
  done
fi
if [[ -z "${SOURCE_INDEX}" || ! -f "${SOURCE_INDEX}" ]]; then
  echo "ERROR: authoritative INDEX.md not found. Set SOURCE_INDEX or ORIGINAL_PARTS_DIR." >&2
  exit 2
fi

FONT_FILE="${FONT_FILE:-}"
FONT_BOLD_FILE="${FONT_BOLD_FILE:-}"
LATIN_FONT_FILE="${LATIN_FONT_FILE:-}"
ARABIC_FONT_BOLD_FILE="${ARABIC_FONT_BOLD_FILE:-}"

if [[ -z "${FONT_FILE}" || ! -f "${FONT_FILE}" ]]; then
  echo "ERROR: FONT_FILE must point to the supplied Persian/Arabic regular font." >&2
  exit 2
fi
if [[ -z "${FONT_BOLD_FILE}" || ! -f "${FONT_BOLD_FILE}" ]]; then
  echo "ERROR: FONT_BOLD_FILE must point to the supplied Latin bold font." >&2
  exit 2
fi
if [[ -z "${LATIN_FONT_FILE}" ]]; then
  font_dir="$(dirname "${FONT_BOLD_FILE}")"
  for candidate in \
    "${font_dir}/SF-Pro-Rounded-Regular (2).otf" \
    "${font_dir}/SF-Pro-Rounded-Regular.otf" \
    "${font_dir}/SF-Pro-Rounded-Medium.otf"; do
    if [[ -f "${candidate}" ]]; then
      LATIN_FONT_FILE="${candidate}"
      break
    fi
  done
fi
if [[ -z "${LATIN_FONT_FILE}" || ! -f "${LATIN_FONT_FILE}" ]]; then
  echo "ERROR: LATIN_FONT_FILE not found. Set it to a supplied Latin regular font." >&2
  exit 2
fi

"${PYTHON}" -c "import importlib.util, weasyprint, pypdf, yaml; assert importlib.util.find_spec('markdown') or importlib.util.find_spec('mistune')" 2>/dev/null || \
  "${PYTHON}" -m pip install weasyprint markdown pypdf pyyaml

mkdir -p "${PDF_DIR}" "$(dirname "${COMBINED_OUTPUT}")"

COMMON_FONT_ARGS=(
  --font-file "${FONT_FILE}"
  --font-bold-file "${FONT_BOLD_FILE}"
  --latin-font-file "${LATIN_FONT_FILE}"
)
if [[ -n "${ARABIC_FONT_BOLD_FILE}" ]]; then
  COMMON_FONT_ARGS+=(--arabic-font-bold-file "${ARABIC_FONT_BOLD_FILE}")
fi
CSS_ARGS=()
if [[ -n "${CSS_FILE}" ]]; then
  CSS_ARGS+=(--css "${CSS_FILE}")
fi
TITLE_ARGS=()
if [[ -n "${BOOK_TITLE}" ]]; then
  TITLE_ARGS+=(--title "${BOOK_TITLE}")
fi

echo "Notes dir       : ${NOTES_DIR}"
echo "Source Index    : ${SOURCE_INDEX}"
echo "PDF dir         : ${PDF_DIR}"
echo "Final PDF       : ${COMBINED_OUTPUT}"
echo "Arabic font     : ${FONT_FILE}"
echo "Latin font      : ${LATIN_FONT_FILE}"
echo "Latin bold font : ${FONT_BOLD_FILE}"

echo "Generating dynamic bilingual Study Index..."
"${PYTHON}" scripts/generate_study_index.py \
  --source-index "${SOURCE_INDEX}" \
  --notes-dir "${NOTES_DIR}" \
  --output "${GENERATED_INDEX}" \
  --metadata-output "${GENERATED_INDEX%.md}.metadata.json"

echo "Building and validating final PDF..."
"${PYTHON}" scripts/create_combined_pdf.py \
  --notes-dir "${NOTES_DIR}" \
  --source-index "${SOURCE_INDEX}" \
  --pdf-dir "${PDF_DIR}" \
  --generated-index "${GENERATED_INDEX}" \
  --output "${COMBINED_OUTPUT}" \
  --report-json "${REPORT_JSON}" \
  --page-number-start "${PAGE_NUMBER_START}" \
  "${COMMON_FONT_ARGS[@]}" \
  "${CSS_ARGS[@]}" \
  "${TITLE_ARGS[@]}"

echo "Done: ${COMBINED_OUTPUT}"
