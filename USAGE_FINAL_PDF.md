# Reference-style PDF output

The PDF stage reads the prepared Markdown, metadata, and Index files only. It does not run or modify Browser Automation.

Every generated session PDF and the final combined PDF use the same built-in reference style:

- dark-blue bilingual Study Index hero
- compact portrait chapter and session tables
- running book/session headers
- session metadata ribbon
- blue Key Points and orange Warning boxes
- embedded supplied fonts
- A4 portrait pages only

## Required environment variables

- `NOTES_DIR`
- `PDF_DIR`
- `ORIGINAL_PARTS_DIR`
- `FONT_FILE`
- `FONT_BOLD_FILE`

`COMBINED_OUTPUT` defaults to `outputs/notes/FINAL_STUDY_NOTES.pdf`.

A font variable may contain multiple supplied font paths separated by `:`, `,`, or `;` when separate Latin and Arabic faces are needed:

```bash
FONT_FILE="/path/Latin-Regular.otf:/path/Arabic-Regular.ttf"
FONT_BOLD_FILE="/path/Latin-Bold.otf:/path/Arabic-Bold.ttf"
```

## Build the final PDF

```bash
./run_notes_to_pdf.sh
```

The combined reference-style PDF is enabled by default. Set `CREATE_COMBINED=0` to render only the individual session PDFs; they keep the same styling and metadata ribbon.

The command exits non-zero on landscape, rotated, or non-A4 pages; unresolved links; invalid destinations or bookmarks; missing or duplicate sessions; unembedded/fallback fonts; broken page labels; or missing visible footer numbers.
