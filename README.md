# ChatGPT Note Maker

End-to-end automation: turn PDFs and raw lecture notes into **clean, well-structured Markdown** using the ChatGPT web UI.

```
PDF / DOCX / Markdown  →  ChatGPT →  Clean .md notes
```

Primarily designed for high-quality **lecture notes rewriting**, but flexible for other prompts (including mind-map OPML generation).

| Mode | Input | Output |
|------|-------|--------|
| **PDF batch** | Folder of PDFs/DOCX/MD | `outputs/notes/*.md` (or opml) |
| **Markdown sections** | One `.md` with `##` headings | Separate clean `.md` per section |

The tool preserves the original logic and flow while making the content much easier to review.

## Requirements

- Python 3.10+
- Google Chrome or Chromium
- ChatGPT account (login once; saved in `chrome_profile/`)
- Linux or Windows

```bash
# Linux — recommended for PyAutoGUI
sudo apt install -y python3-tk python3-dev chromium-browser
```

## Quick Start

### Setup (once)

```bash
cd note-maker
chmod +x setup.sh run_pdf_to_notes.sh run_md_to_notes.sh
./setup.sh
```

Windows: run `setup.cmd`.

### PDF → Clean Markdown Notes (recommended)

```bash
# Put your PDFs / DOCX in inputs/
./run_pdf_to_notes.sh --overwrite

# Or with env vars
INPUT_DIR=/path/to/pdfs NOTES_DIR=/path/to/output ./run_pdf_to_notes.sh --overwrite
```

### Markdown file (with ## sections) → Notes

```bash
MARKDOWN_FILE=your_lecture.md ./run_md_to_notes.sh --overwrite

# Only selected sections
MARKDOWN_FILE=your_lecture.md SECTIONS=2,5-9 ./run_md_to_notes.sh --overwrite
```

### Legacy mind-map (OPML → XMind)

The original mind-map pipeline is still available:

```bash
./run_pdf_to_xmind.sh --overwrite
# or
MARKDOWN_FILE=notes.md ./run_md_to_xmind.sh
```

## Project Structure

```
note-maker/
├── README.md
├── requirements.txt
├── setup.sh / setup.cmd
├── run_pdf_to_notes.sh          # PDF → clean Markdown notes (new main flow)
├── run_md_to_notes.sh           # Markdown sections → clean .md notes
├── run_pdf_to_xmind.sh ...      # Legacy mind-map flows
├── prompts/
│   ├── prompt-rewrite-notes.md  # Lecture notes → structured Markdown (recommended)
│   └── prompt-mind-map.md       # Original mind-map prompt
├── scripts/
│   ├── batch_pdf.py
│   ├── batch_markdown.py
│   ├── run_chatgpt_temporary_test.py   # Core Selenium automation
│   └── ...
├── inputs/
└── outputs/notes/       # Default output for rewritten notes
```

## Pipeline Steps

1. Upload source (PDF or Markdown section) to a fresh temporary ChatGPT chat.
2. Send your prompt (e.g. the notes rewriter).
3. ChatGPT generates the file (`.md` or `.opml`) and the automation downloads it automatically.
4. (Optional) Post-processing (for mind-maps: convert OPML → XMind).

## CLI Options (pipeline)

Passed through to the underlying steps:

| Flag | Description |
|------|-------------|
| `--overwrite` | Re-generate existing OPML and XMind files |
| `--limit N` | Process only first N files/sections |
| `--model "Name"` | ChatGPT model label (e.g. `GPT-4o`) |
| `--save-diagnostics` | Save response text + screenshot per item |
| `--sections 1,3,5-8` | Markdown mode: filter sections |
| `--no-warm-up` | Skip the initial hello warm-up message |
| `--keep-browser` | Leave browser open after batch finishes |

## Customizing the Prompt

Edit any file in `prompts/`.

- `prompt-rewrite-notes.md` — Current main prompt for clean lecture notes (recommended).
- `prompt-mind-map.md` — Original prompt for OPML mind maps.

The automation works with any prompt as long as ChatGPT is told to **save the result as a downloadable file** and reply with **only the download link**.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Browser not found | Install Chrome/Chromium |
| Not logged in | Log in manually in the opened browser |
| No OPML downloaded | Use `--save-diagnostics`; check `downloads/` |
| XMind won't open | Re-run `./run_opml_to_xmind.sh` on existing OPML |
| Wrong model | Pass `--model "GPT-4o"` |
| Browser restarts every file | Use one batch run with multiple sections; retries now reset chat only |
| `Could not load temporary chat` / prompt editor missing | Automation cookies (`conv_key_*`) piled up. Batches auto-prune at start and after each file; manual fix: `python3 scripts/prune_chatgpt_cookies.py` (login is preserved) |

## Portability

Copy this folder anywhere. Run `setup.sh`, log in once, point `INPUT_DIR` / `MARKDOWN_FILE` / `XMIND_DIR` to your paths. No hardcoded user paths.

## Related

The original mind-map functionality is still fully supported. This project was forked and rebranded from the mind-map automation for the new lecture notes rewriting workflow.

---

## PDF Export (Integrated)

You can now generate both clean `.md` **and** beautiful study PDFs in one go:

```bash
# PDF/MD files → notes + PDFs
DO_PDF=1 ./run_pdf_to_notes.sh --overwrite

# Or using flag (passed through)
./run_pdf_to_notes.sh --pdf --overwrite

# Markdown sections → notes + PDFs
DO_PDF=1 MARKDOWN_FILE=your_notes.md ./run_md_to_notes.sh --overwrite

# Or explicitly set output dirs
INPUT_DIR=inputs NOTES_DIR=outputs/notes PDF_DIR=outputs/pdfs DO_PDF=1 ./run_pdf_to_notes.sh
```

### Combined PDF with فهرست (Index)

When processing a whole folder, automatically create **one big PDF**:

- First page: clean **Table of Contents / فهرست** listing all titles
- Then all the individual notes combined in order

```bash
# Full flow: .md + individual PDFs + combined with index
DO_PDF=1 CREATE_COMBINED=1 ./run_pdf_to_notes.sh --overwrite

# Custom combined file name
DO_PDF=1 CREATE_COMBINED=1 COMBINED_OUTPUT=outputs/My_Complete_Notes.pdf ./run_pdf_to_notes.sh
```

Standalone (if you already have the PDFs):

```bash
python scripts/create_combined_pdf.py \
  --notes-dir outputs/notes \
  --pdf-dir outputs/pdfs \
  --output outputs/COMBINED_NOTES.pdf
```

Uses WeasyPrint + clean academic styling (A4, readable typography, highlighted "Key Points" box, page numbers).

This produces PDFs in a similar professional style to your Obsidian study material exports.

## Customizing / Extending

- Main prompt for notes: `prompts/prompt-rewrite-notes.md`
- You can add new prompts and use `--prompt your-prompt.md --output-ext md`

The core automation works for any prompt that makes ChatGPT produce a downloadable file.
