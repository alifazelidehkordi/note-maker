#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  if [[ -x ".venv-linux/bin/python" ]]; then
    PYTHON=".venv-linux/bin/python"
  else
    PYTHON="python3"
  fi
fi

NOTES_DIR="${NOTES_DIR:-outputs/notes}"
PDF_DIR="${PDF_DIR:-${NOTES_DIR}/pdfs}"
ORIGINAL_PARTS_DIR="${ORIGINAL_PARTS_DIR:-${NOTES_DIR}}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-outputs/notes/FINAL_STUDY_NOTES.pdf}"
INDEX_MD="${INDEX_MD:-}"
CSS_FILE="${CSS_FILE:-}"
BOOK_TITLE="${BOOK_TITLE:-}"
QA_REPORT="${QA_REPORT:-${COMBINED_OUTPUT%.pdf}_QA.json}"
BUILD_INDIVIDUAL_PDFS="${BUILD_INDIVIDUAL_PDFS:-0}"

: "${FONT_FILE:?FONT_FILE is required. It may contain path-separated supplied regular font files.}"
: "${FONT_BOLD_FILE:?FONT_BOLD_FILE is required. It may contain path-separated supplied bold font files.}"

[[ -d "$NOTES_DIR" ]] || { echo "ERROR: NOTES_DIR not found: $NOTES_DIR" >&2; exit 2; }
[[ -d "$ORIGINAL_PARTS_DIR" ]] || { echo "ERROR: ORIGINAL_PARTS_DIR not found: $ORIGINAL_PARTS_DIR" >&2; exit 2; }

IFS=':' read -r -a REGULAR_FONTS <<< "$FONT_FILE"
IFS=':' read -r -a BOLD_FONTS <<< "$FONT_BOLD_FILE"
for font in "${REGULAR_FONTS[@]}" "${BOLD_FONTS[@]}"; do
  [[ -r "$font" ]] || { echo "ERROR: supplied font is not readable: $font" >&2; exit 2; }
done

mkdir -p "$PDF_DIR" "$(dirname "$COMBINED_OUTPUT")" "$(dirname "$QA_REPORT")"

# Keep the prepared Index authoritative. Some prepared packages use a flat
# "Recommended sequence" and store chapter names in the existing Major division
# field. Normalize only that structure/markup into a temporary parser-compatible
# Index; no content is generated or fetched.
NORMALIZED_INDEX="$(mktemp "${TMPDIR:-/tmp}/note-maker-index.XXXXXX.md")"
trap 'rm -f "$NORMALIZED_INDEX"' EXIT
NORMALIZE_ARGS=(--notes-dir "$NOTES_DIR" --output "$NORMALIZED_INDEX")
[[ -n "$INDEX_MD" ]] && NORMALIZE_ARGS+=(--index-md "$INDEX_MD")
"$PYTHON" scripts/normalize_prepared_index.py "${NORMALIZE_ARGS[@]}" >/dev/null

COMMON_ARGS=(--index-md "$NORMALIZED_INDEX")
[[ -n "$CSS_FILE" ]] && COMMON_ARGS+=(--css "$CSS_FILE")
[[ -n "$BOOK_TITLE" ]] && COMMON_ARGS+=(--title "$BOOK_TITLE")

printf '%s\n' "=== Note Maker: final study-book PDF ===" \
  "Notes dir       : $NOTES_DIR" \
  "Original parts  : $ORIGINAL_PARTS_DIR" \
  "PDF dir         : $PDF_DIR" \
  "Combined output : $COMBINED_OUTPUT" \
  "QA report       : $QA_REPORT"

# Browser Automation is intentionally not invoked. Input Markdown and Index files
# are treated as complete, final inputs.

if [[ "$BUILD_INDIVIDUAL_PDFS" == "1" ]]; then
  INDIVIDUAL_ARGS=()
  [[ -n "$CSS_FILE" ]] && INDIVIDUAL_ARGS+=(--css "$CSS_FILE")
  "$PYTHON" scripts/convert_md_to_pdf.py \
    --batch "$NOTES_DIR" \
    --output "$PDF_DIR" \
    "${INDIVIDUAL_ARGS[@]}"
fi

"$PYTHON" scripts/create_combined_pdf.py \
  --notes-dir "$NOTES_DIR" \
  --pdf-dir "$PDF_DIR" \
  --output "$COMBINED_OUTPUT" \
  --qa-report "$QA_REPORT" \
  "${COMMON_ARGS[@]}"

printf '\nCreated files:\n'
ls -lh "$COMBINED_OUTPUT" "$QA_REPORT" "${QA_REPORT%.json}.txt"
