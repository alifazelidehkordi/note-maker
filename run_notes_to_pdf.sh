#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

NOTES_DIR="${NOTES_DIR:-outputs/notes}"
COMBINED_OUTPUT="${COMBINED_OUTPUT:-outputs/notes/FINAL_STUDY_NOTES.pdf}"
INDEX_MD="${INDEX_MD:-}"
BOOK_TITLE="${BOOK_TITLE:-}"

if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif [[ -x ".venv-linux/bin/python" ]]; then
  PY=".venv-linux/bin/python"
else
  PY="python"
fi

if ! "$PY" -c 'import fitz, mistune, pypdf, reportlab, weasyprint' >/dev/null 2>&1; then
  if [[ -x "./setup.sh" ]]; then
    ./setup.sh
    PY=".venv-linux/bin/python"
  elif [[ -f "requirements.txt" ]]; then
    "$PY" -m pip install -r requirements.txt
  else
    echo "Missing PDF dependencies and no setup.sh/requirements.txt available." >&2
    exit 2
  fi
fi

ARGS=(--notes-dir "$NOTES_DIR" --output "$COMBINED_OUTPUT" --repo .)
[[ -n "$INDEX_MD" ]] && ARGS+=(--index-md "$INDEX_MD")
[[ -n "$BOOK_TITLE" ]] && ARGS+=(--title "$BOOK_TITLE")

"$PY" scripts/create_combined_pdf.py "${ARGS[@]}"
