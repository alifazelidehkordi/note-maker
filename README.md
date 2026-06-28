# ChatGPT Note Maker

Turn lecture PDFs and raw notes into **clean, study-ready Markdown** — then optionally export **styled PDFs** with a rich Persian/English فهرست, chapter tables, and original page mappings.

```
PDF / DOCX / Markdown  →  ChatGPT  →  Clean .md notes  →  Study PDFs + Combined book
```

Built for medical and university study workflows (tested on 39-topic pathophysiology corpora), but works with any prompt that makes ChatGPT return a downloadable file.

## What it does

| Stage | Input | Output |
|-------|-------|--------|
| **Rewrite** | PDFs, DOCX, or `##` sections in one `.md` | Clean notes in `outputs/notes/` |
| **Enrich** *(optional)* | Original split parts with `pdf_pages` frontmatter | Metadata copied into rewritten notes |
| **Rich index** *(optional)* | Parts + rewritten notes | `STUDY_INDEX-rewritten.md` (فصول، جلسات، صفحات، تمرکز مطالعه) |
| **PDF export** | Rewritten `.md` topic notes | Individual PDFs via WeasyPrint |
| **Combined book** | Notes + index | One PDF: rich فهرست first, then all topics in order |

## Requirements

- Python 3.10+
- Google Chrome or Chromium
- ChatGPT account (log in once; session saved in `chrome_profile/`)
- Linux or Windows

```bash
# Linux — PyAutoGUI + browser automation
sudo apt install -y python3-tk python3-dev chromium-browser
```

## Quick start

### 1. Setup (once)

```bash
git clone https://github.com/alifazelidehkordi/note-maker.git
cd note-maker
chmod +x setup.sh run_*.sh
./setup.sh
```

Windows: run `setup.cmd`.

### 2. PDF → clean Markdown notes

```bash
# Put PDFs/DOCX in inputs/
./run_pdf_to_notes.sh --overwrite
```

### 3. Markdown with `##` sections → notes

```bash
MARKDOWN_FILE=your_lecture.md ./run_md_to_notes.sh --overwrite
SECTIONS=2,5-9 MARKDOWN_FILE=your_lecture.md ./run_md_to_notes.sh --overwrite
```

### 4. PDF export only (notes already exist)

```bash
NOTES_DIR=outputs/phisiopath-full \
PDF_DIR=outputs/phisiopath-full/pdfs \
CREATE_COMBINED=1 \
INDEX_MD=outputs/phisiopath-full/STUDY_INDEX-rewritten.md \
./run_notes_to_pdf.sh
```

Or the one-liner wrapper:

```bash
./run_notes_to_pdf.sh   # defaults: outputs/notes → outputs/pdfs
```

## Full PDF pipeline (فهرست غنی + combined)

When you have **original topic parts** (with `pdf_pages` in frontmatter) and **rewritten notes**:

```bash
ORIGINAL_PARTS_DIR=/path/to/original-parts \
NOTES_DIR=outputs/clean-notes \
PDF_DIR=outputs/clean-notes/pdfs \
DO_PDF=1 CREATE_COMBINED=1 \
ENRICH_SOURCE=1 GENERATE_RICH_INDEX=1 \
./run_pdf_to_notes.sh --overwrite
```

**Order of operations (wired correctly):**

1. `enrich_rewritten_notes.py` — copy `pdf_pages`, `chapter`, `part` into clean notes  
2. `generate_study_index.py` — build `STUDY_INDEX-rewritten.md`  
3. `convert_md_to_pdf.py` — topic notes only (`01_01_...` pattern, 39 files)  
4. `create_combined_pdf.py` — **rich index as opening pages**, then all topic PDFs  

The combined PDF auto-detects `STUDY_INDEX-rewritten.md` beside the notes folder. Override with `INDEX_MD=/path/to/index.md`.

### PDF styling options

```bash
# Themes: medical-blue (default), ink, emerald
# Presets: study, compact, comfortable, print
.venv-linux/bin/python scripts/convert_md_to_pdf.py notes/01_01_Topic.md \
  --theme emerald --preset compact --rtl

# Custom Obsidian-like CSS
CSS_FILE=~/.obsidian/print.css ./run_notes_to_pdf.sh

# Disable auto RTL detection for Persian content
.venv-linux/bin/python scripts/convert_md_to_pdf.py notes --batch --output pdfs --no-auto-rtl
```

**Key Points** and **Warnings / هشدارها** sections are auto-highlighted. YAML frontmatter and `منبع اصلی` lines are stripped from PDF output.

## Project layout

```
note-maker/
├── run_pdf_to_notes.sh       # Main: PDF/DOCX → ChatGPT → .md (+ optional PDF)
├── run_md_to_notes.sh        # Markdown sections → .md (+ optional PDF)
├── run_notes_to_pdf.sh       # Existing .md → PDFs + combined book
├── run_tests.sh              # Full unit test suite
├── prompts/
│   ├── prompt-rewrite-notes.md   # Lecture notes rewriter (recommended)
│   └── prompt-mind-map.md        # Legacy OPML mind-map prompt
├── scripts/
│   ├── batch_pdf.py / batch_markdown.py
│   ├── convert_md_to_pdf.py      # WeasyPrint study PDFs
│   ├── create_combined_pdf.py    # Rich index + merge
│   ├── enrich_rewritten_notes.py
│   ├── generate_study_index.py   # Rich فهرست generator
│   └── run_chatgpt_temporary_test.py
├── inputs/                   # Default input folder
└── outputs/                  # Generated notes & PDFs (gitignored)
```

## Testing

```bash
./run_tests.sh
# or
npm test
```

16 tests cover download detection, PDF helpers, RTL detection, preset application, and a WeasyPrint smoke test.

## CLI flags (ChatGPT batch)

| Flag | Description |
|------|-------------|
| `--overwrite` | Re-generate existing outputs |
| `--limit N` | Process only first N files/sections |
| `--model "Name"` | ChatGPT model label |
| `--pdf` / `DO_PDF=1` | Also generate PDFs after rewrite |
| `--combined` / `CREATE_COMBINED=1` | Build combined PDF with index |
| `--save-diagnostics` | Save response text + screenshot per item |
| `--sections 1,3,5-8` | Markdown mode: filter sections |

### Environment variables (PDF stage)

| Variable | Default | Purpose |
|----------|---------|---------|
| `NOTES_DIR` | `outputs/notes` | Rewritten markdown folder |
| `PDF_DIR` | `NOTES_DIR/pdfs` | Individual PDF output |
| `CREATE_COMBINED` | `0` | Build merged PDF |
| `COMBINED_OUTPUT` | `NOTES_DIR/../COMBINED_NOTES.pdf` | Combined file path |
| `ENRICH_SOURCE` | `0` | Copy page metadata from original parts |
| `GENERATE_RICH_INDEX` | `0` | Generate `STUDY_INDEX-rewritten.md` |
| `ORIGINAL_PARTS_DIR` | — | Source parts for enrich + index |
| `INDEX_MD` | auto-detect | Rich index for combined PDF front matter |
| `CSS_FILE` | — | Extra print CSS (e.g. Obsidian theme) |

## Custom prompts

Edit files in `prompts/`. ChatGPT must be instructed to **save the result as a downloadable file** and reply with **only the download link**.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Browser not found | Install Chrome/Chromium |
| Not logged in | Log in manually in the opened browser |
| Download not detected | `--save-diagnostics`; check `downloads/` |
| `temporary chat` / editor missing | `python3 scripts/prune_chatgpt_cookies.py` |
| PDF deps missing | `pip install weasyprint markdown pypdf` or re-run `./setup.sh` |
| Combined PDF has wrong index | Ensure `STUDY_INDEX-rewritten.md` exists; set `INDEX_MD` explicitly |
| Wrong ChatGPT model | `--model "GPT-4o"` |

## Legacy mind-map flow

OPML → XMind is still supported:

```bash
./run_pdf_to_xmind.sh --overwrite
./run_opml_to_xmind.sh
```

## Portability

Copy the folder anywhere. Run `setup.sh`, log in once, point `INPUT_DIR` / `NOTES_DIR` / `MARKDOWN_FILE` to your paths. No hardcoded user directories.

## License

Private study automation tooling. Use and modify for personal academic workflows.