# ChatGPT Note Maker

[![Tests](https://img.shields.io/badge/tests-16%20passing-brightgreen)](#testing)

Automate lecture-note workflows with the **ChatGPT web UI**: upload sources, apply a custom prompt, download clean Markdown — then optionally build **study PDFs** with a rich study index, chapter tables, and links back to original PDF page ranges.

Designed for dense medical/university material (validated on a **39-topic pathophysiology** corpus), but any prompt that makes ChatGPT return a **downloadable file** works.

```
┌─────────────┐    ┌──────────┐    ┌────────────────┐    ┌─────────────────────────────┐
│ PDF / DOCX  │───▶│ ChatGPT  │───▶│ Clean .md notes │───▶│ PDFs + combined study book  │
│ or .md ##   │    │  (web)   │    │  (structured)   │    │  (WeasyPrint + rich index)  │
└─────────────┘    └──────────┘    └────────────────┘    └─────────────────────────────┘
```

---

## Table of contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Workflows](#workflows)
- [Rich study index (STUDY_INDEX)](#rich-study-index-study_index)
- [PDF export & styling](#pdf-export--styling)
- [Output note format](#output-note-format)
- [Shell scripts reference](#shell-scripts-reference)
- [Python scripts reference](#python-scripts-reference)
- [Environment variables](#environment-variables)
- [CLI reference](#cli-reference)
- [Project structure](#project-structure)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Quick start](#quick-start)
- [Choose your workflow](#choose-your-workflow)
- [How ChatGPT automation works](#how-chatgpt-automation-works)
- [Legacy mind-map pipeline](#legacy-mind-map-pipeline)
- [Portability & privacy](#portability--privacy)

---

## Features

| Capability | Description |
|------------|-------------|
| **Batch rewrite** | Process a folder of PDFs/DOCX or split a long Markdown file by `##` headings |
| **Selenium automation** | Opens temporary ChatGPT chats, attaches files, sends prompts, downloads artifacts |
| **Structured notes** | Default prompt enforces `# Title` → `## Explanation` → `## Key Points` |
| **Metadata enrichment** | Copy `pdf_pages`, `chapter`, `part` from original split parts into rewritten notes |
| **Rich study index** | Generate `STUDY_INDEX-rewritten.md` with chapters, sessions, original page ranges, and study-focus columns |
| **Study PDFs** | WeasyPrint export with medical-blue theme, RTL auto-detection, Key Points highlighting |
| **Combined book** | One PDF: rich index pages first, then all topic notes in order |
| **Mind maps** | Legacy OPML generation + conversion to themed XMind files |
| **Resilient batches** | Cookie pruning, chat recovery, retries, skip-existing, diagnostics mode |

---

## Requirements

| Dependency | Purpose |
|------------|---------|
| Python 3.10+ | All automation scripts |
| Google Chrome / Chromium | ChatGPT web UI |
| ChatGPT account | Log in once; session stored in `chrome_profile/` |
| Linux or Windows | `.sh` / `.cmd` runners for both |

**Linux system packages** (PyAutoGUI + browser):

```bash
sudo apt install -y python3-tk python3-dev chromium-browser
```

**Python packages** (`requirements.txt`):

```
selenium  pyautogui  pyperclip  markdown  weasyprint  pypdf  pyyaml
```

`pyyaml` is required for `generate_study_index.py` and `enrich_rewritten_notes.py` (installed automatically via `setup.sh` if missing).

---

## Installation

```bash
git clone https://github.com/alifazelidehkordi/note-maker.git
cd note-maker
chmod +x setup.sh run_*.sh
./setup.sh          # creates .venv-linux, installs deps
```

**Windows:** run `setup.cmd`.

**First ChatGPT run:** a browser window opens — log in manually. The profile is reused for all future batches.

**WeasyPrint on Linux** (PDF export only — skip if you only need Markdown):

```bash
sudo apt install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
  libffi-dev shared-mime-info fonts-vazirmatn fonts-noto-core
```

---

## Quick start

```bash
# 1. Rewrite PDFs in inputs/ → clean Markdown
./run_pdf_to_notes.sh --overwrite

# 2. Export study PDFs from existing notes
./run_notes_to_pdf.sh

# 3. Full book: enrich metadata + rich study index + PDFs + combined
ORIGINAL_PARTS_DIR=/path/to/parts DO_PDF=1 CREATE_COMBINED=1 \
  ENRICH_SOURCE=1 GENERATE_RICH_INDEX=1 ./run_pdf_to_notes.sh --overwrite
```

---

## Choose your workflow

| You have… | Run this | You get… |
|-----------|----------|----------|
| PDFs or DOCX in `inputs/` | `run_pdf_to_notes.sh` | Rewritten `.md` in `outputs/notes/` |
| One long `.md` with `##` sections | `run_md_to_notes.sh` | One `.md` per section |
| Clean notes already on disk | `run_notes_to_pdf.sh` | Individual PDFs (+ optional combined book) |
| Original parts + rewritten notes | `run_notes_to_pdf.sh` with `ENRICH_SOURCE=1` | Notes with `pdf_pages` frontmatter |
| Parts + notes, need study index | Add `GENERATE_RICH_INDEX=1` | `STUDY_INDEX-rewritten.md` |
| Everything in one shot | `run_pdf_to_notes.sh` with all `DO_PDF` flags | Rewrite → enrich → index → PDF → combined |
| OPML mind maps (legacy) | `run_pdf_to_xmind.sh` | OPML + themed XMind files |

---

## Workflows

### 1. PDF / DOCX → clean Markdown (main flow)

```bash
# Drop files in inputs/
./run_pdf_to_notes.sh --overwrite

# Custom paths
INPUT_DIR=/path/to/pdfs NOTES_DIR=/path/to/output ./run_pdf_to_notes.sh --overwrite

# Custom prompt
PROMPT_FILE=prompts/prompt-mind-map.md ./run_pdf_to_notes.sh --output-ext opml
```

**What happens:**
1. `batch_pdf.py` uploads each file to a fresh temporary ChatGPT chat
2. Sends `prompts/prompt-rewrite-notes.md` (or your custom prompt)
3. Detects and downloads the `.md` artifact
4. Saves to `outputs/notes/` (or your `NOTES_DIR`)
5. Writes `logs/last_batch_summary.json`

### 2. Single Markdown file → one note per `##` section

```bash
MARKDOWN_FILE=lecture.md ./run_md_to_notes.sh --overwrite

# Only sections 2, 5, 6, 7, 8, 9
SECTIONS=2,5-9 MARKDOWN_FILE=lecture.md ./run_md_to_notes.sh --overwrite
```

### 3. PDF export only (notes already on disk)

When ChatGPT rewriting is done and you only need PDFs:

```bash
NOTES_DIR=outputs/phisiopath-full \
PDF_DIR=outputs/phisiopath-full/pdfs \
CREATE_COMBINED=1 \
INDEX_MD=outputs/phisiopath-full/STUDY_INDEX-rewritten.md \
./run_notes_to_pdf.sh
```

Defaults if you omit env vars: `outputs/notes` → `outputs/pdfs`.

### 4. Full pipeline: rewrite + enrich + study index + PDF + combined

For corpora split into **topic parts** with YAML frontmatter (`pdf_pages`, `chapter`, `part`):

```bash
ORIGINAL_PARTS_DIR=/path/to/original-parts \
NOTES_DIR=outputs/clean-notes \
PDF_DIR=outputs/clean-notes/pdfs \
DO_PDF=1 \
CREATE_COMBINED=1 \
ENRICH_SOURCE=1 \
GENERATE_RICH_INDEX=1 \
./run_pdf_to_notes.sh --overwrite
```

**Pipeline order (wired in `run_pdf_to_notes.sh`):**

| Step | Script | Output |
|------|--------|--------|
| 1 | `batch_pdf.py` | Rewritten `.md` topic notes |
| 2 | `enrich_rewritten_notes.py` | Frontmatter with original page mapping |
| 3 | `generate_study_index.py` | `STUDY_INDEX-rewritten.md` |
| 4 | `convert_md_to_pdf.py` | Individual PDFs (topic files only) |
| 5 | `create_combined_pdf.py` | Combined PDF with rich index front matter |

### 5. Real-world example: `phisiopath-full`

A 39-session pathophysiology corpus:

```
outputs/phisiopath-full/
├── 01_01_Blood_Cells_....md          # 39 topic notes
├── ...
├── 09_39_Hypoparathyroidism.md
├── STUDY_INDEX-rewritten.md          # Rich study index (auto-generated)
├── pdfs/                             # Individual study PDFs
└── COMBINED_NOTES.pdf                # Index + all 39 topics (~243 pages)
```

Regenerate PDFs from existing notes:

```bash
NOTES_DIR=outputs/phisiopath-full \
PDF_DIR=outputs/phisiopath-full/pdfs \
CREATE_COMBINED=1 \
COMBINED_OUTPUT=outputs/phisiopath-full/COMBINED_NOTES.pdf \
./run_notes_to_pdf.sh
```

---

## Rich study index (STUDY_INDEX)

`generate_study_index.py` builds a structured study index modeled on medical course layout:

**Sections included:**
- **Overview** — session count and course summary
- **Chapter index** — table of chapters (chapter, topic, sessions, pages)
- **Per-chapter tables** — session, topic, original pages, study focus
- **Quick-reference summary** — compact mirror of the same structure

**Standalone generation:**

```bash
python scripts/generate_study_index.py \
  --parts-dir /path/to/original-parts \
  --clean-dir outputs/phisiopath-full \
  --original-index /path/to/STUDY_INDEX-phisiopath.md \
  --output outputs/phisiopath-full/STUDY_INDEX-rewritten.md \
  --title "Physiopathology (Rewritten)"
```

**Combined PDF integration:** `create_combined_pdf.py` auto-detects `STUDY_INDEX-rewritten.md` (or `STUDY_INDEX.md`) next to the notes folder and renders it as the **opening pages** of the merged PDF. Override with `--index-md` or `INDEX_MD=...`.

**Topic file filter:** Only files matching the `NN_NN_` prefix (e.g. `01_01_Blood_Cells_....md`, `09_39_Hypoparathyroidism.md`) are treated as study topics. Meta files (`STUDY_INDEX-*`, `COMBINED_NOTES`) are excluded from batch PDF conversion and the combined body.

### Original parts frontmatter

Topic-split source files should carry YAML frontmatter so enrichment and the study index can map sessions to original PDF pages:

```yaml
---
part: 1
chapter: 1
title: "Blood Cells, Haematopoiesis, and Growth Factors"
pdf_pages: "1-8"
book_pages: "—"
source: "lecture-slides.pdf"
---
```

`enrich_rewritten_notes.py` copies `pdf_pages`, `book_pages`, `source`, `chapter`, and `part` into rewritten notes when filenames match between `ORIGINAL_PARTS_DIR` and `NOTES_DIR`.

---

## How ChatGPT automation works

1. **Browser profile** — Selenium launches Chrome/Chromium with a persistent `chrome_profile/` (login cookies survive between runs).
2. **Temporary chats** — Each input file opens a fresh ChatGPT chat (avoids context bleed between lectures).
3. **Upload & prompt** — The file is attached, then the full text of `PROMPT_FILE` is sent.
4. **Download detection** — The script waits for a new file in `downloads/`, matching `.md`, `.opml`, or other `--output-ext`.
5. **Batch resilience** — Failed items retry up to 3 times; `--save-diagnostics` captures the last assistant reply and a screenshot.
6. **Summary log** — `logs/last_batch_summary.json` records per-file success, timing, and errors.

Inputs named `00_INDEX*`, `INDEX`, or `README` are skipped automatically in batch folders.

---

## PDF export & styling

Powered by `scripts/convert_md_to_pdf.py` (WeasyPrint).

### Themes

| Theme | Style |
|-------|-------|
| `medical-blue` *(default)* | Blue headings, soft Key Points boxes |
| `ink` | Neutral grayscale, print-friendly |
| `emerald` | Green accent, calm reading |

### Layout presets

| Preset | Use case |
|--------|----------|
| `study` *(default)* | Balanced density for daily review |
| `compact` | More content per page |
| `comfortable` | Larger type, more margin — long sessions |
| `print` | Conservative ink usage |

### Examples

```bash
# Single file with RTL + compact layout
python scripts/convert_md_to_pdf.py note.md --rtl --preset compact --theme emerald

# Batch folder
python scripts/convert_md_to_pdf.py outputs/phisiopath-full --batch \
  --output outputs/phisiopath-full/pdfs

# Obsidian print CSS overlay
CSS_FILE=~/.obsidian/print.css ./run_notes_to_pdf.sh

# Letter size, no page numbers
python scripts/convert_md_to_pdf.py note.md --page-size Letter --no-page-numbers
```

### PDF processing details

- Strips YAML frontmatter and source-metadata lines (e.g. `pdf_pages:`)
- Wraps **Key Points** and **Warnings** headings (including localized variants) in styled boxes
- Auto-detects Persian/Arabic script → enables RTL layout (disable with `--no-auto-rtl`)
- Supports tables, footnotes, fenced code, TOC extension
- Uses Vazirmatn / Noto Arabic font stack for mixed Persian/English notes

### Combined PDF

```bash
python scripts/create_combined_pdf.py \
  --notes-dir outputs/phisiopath-full \
  --pdf-dir outputs/phisiopath-full/pdfs \
  --index-md outputs/phisiopath-full/STUDY_INDEX-rewritten.md \
  --output outputs/phisiopath-full/COMBINED_NOTES.pdf
```

---

## Output note format

The default rewriter prompt (`prompts/prompt-rewrite-notes.md`) enforces:

```markdown
# Main Title

## Explanation
### Optional subheading
Structured content with **bold key terms**, clear mechanisms, cause→effect chains.

## Key Points
- 5–8 high-yield bullets for rapid review
```

ChatGPT must save the result as a downloadable `.md` file and reply with **only the download link** — the automation depends on this behavior.

---

## Shell scripts reference

| Script | Purpose |
|--------|---------|
| `setup.sh` / `setup.cmd` | Create venv, install Python deps |
| `run_pdf_to_notes.sh` | **Main:** PDF/DOCX → ChatGPT → `.md` (+ optional PDF pipeline) |
| `run_md_to_notes.sh` | Markdown `##` sections → `.md` notes (+ optional PDF) |
| `run_notes_to_pdf.sh` | Existing `.md` → PDFs + optional combined book |
| `run_pdf_to_xmind.sh` | PDF → ChatGPT → OPML → XMind (legacy) |
| `run_md_to_xmind.sh` | Markdown sections → OPML → XMind |
| `run_pdf_batch.sh` | OPML-only batch (no XMind step) |
| `run_md_batch.sh` | Markdown batch wrapper |
| `run_opml_to_xmind.sh` | Convert existing OPML folder to XMind |
| `run_tests.sh` | Run full unit test suite |

All `run_*.sh` scripts accept forwarded flags (`--overwrite`, `--limit`, `--model`, etc.).

---

## Python scripts reference

| Script | Role |
|--------|------|
| `run_chatgpt_temporary_test.py` | Core Selenium driver: browser, chat, upload, download detection |
| `batch_pdf.py` | Batch processor for PDF/DOCX/MD inputs |
| `batch_markdown.py` | Split Markdown by `##`, process each section |
| `batch_common.py` | Shared batch utilities: retries, cookies, logging |
| `pipeline.py` | Unified CLI for PDF or Markdown → OPML/MD → XMind chains |
| `convert_md_to_pdf.py` | Markdown → styled study PDF (WeasyPrint) |
| `create_combined_pdf.py` | Rich index + topic PDFs → one merged book |
| `enrich_rewritten_notes.py` | Copy `pdf_pages` metadata from original parts |
| `generate_study_index.py` | Build rich `STUDY_INDEX-rewritten.md` |
| `convert_opml_to_xmind.py` | Single OPML → themed `.xmind` |
| `convert_opml_batch.py` | Batch OPML → XMind |
| `opml_utils.py` | OPML repair and validation |
| `prune_chatgpt_cookies.py` | Fix piled-up `conv_key_*` cookies (keeps login) |

---

## Environment variables

### ChatGPT rewrite stage

| Variable | Default | Description |
|----------|---------|-------------|
| `INPUT_DIR` | `inputs` | Source PDFs/DOCX for batch |
| `MARKDOWN_FILE` | — | Single `.md` file for section mode |
| `NOTES_DIR` | `outputs/notes` | Output folder for rewritten `.md` |
| `PROMPT_FILE` | `prompts/prompt-rewrite-notes.md` | ChatGPT system prompt |
| `SECTIONS` | all | Section filter, e.g. `2,5-9` |

### PDF stage

| Variable | Default | Description |
|----------|---------|-------------|
| `DO_PDF` | `0` | Set `1` to enable PDF export after rewrite |
| `PDF_DIR` | `NOTES_DIR/pdfs` | Individual PDF output folder |
| `CREATE_COMBINED` | `0` | Set `1` to build merged PDF |
| `COMBINED_OUTPUT` | `NOTES_DIR/../COMBINED_NOTES.pdf` | Combined PDF path |
| `ENRICH_SOURCE` | `0` | Copy page metadata from original parts |
| `GENERATE_RICH_INDEX` | `0` | Generate `STUDY_INDEX-rewritten.md` |
| `ORIGINAL_PARTS_DIR` | — | Source parts for enrich + index steps |
| `INDEX_MD` | auto-detect | Rich index file for combined PDF |
| `CSS_FILE` | — | Extra CSS appended to PDF styles |

### Paths & artifacts

| Path | Contents |
|------|----------|
| `inputs/` | Default batch input (PDF, DOCX, `.md`) |
| `outputs/notes/` | Default rewritten Markdown output |
| `outputs/pdfs/` | Individual study PDFs (when `DO_PDF=1`) |
| `downloads/` | ChatGPT browser downloads (staging) |
| `logs/last_batch_summary.json` | Last batch run report |
| `chrome_profile/` | Persistent browser session (local only) |

---

## CLI reference

### Shared batch flags (passed through shell scripts)

| Flag | Description |
|------|-------------|
| `--overwrite` | Re-generate files that already exist |
| `--limit N` | Process only first N items |
| `--model "GPT-4o"` | ChatGPT model label in UI |
| `--save-diagnostics` | Save response text + screenshot per item |
| `--no-warm-up` | Skip initial hello message |
| `--keep-browser` | Leave browser open after batch |
| `--pdf` | Alias for `DO_PDF=1` |
| `--combined` | Alias for `CREATE_COMBINED=1` |
| `--sections 1,3,5-8` | Markdown mode: filter sections |

### `convert_md_to_pdf.py`

```
python scripts/convert_md_to_pdf.py <file-or-dir> [--batch] [--output PATH]
  --theme {medical-blue,ink,emerald}
  --preset {study,compact,comfortable,print}
  --rtl  --no-auto-rtl
  --css FILE  --page-size A4  --margin "1.4cm 1.6cm"
  --font-size 10.5pt  --line-height 1.5  --no-page-numbers
```

---

## Project structure

```
note-maker/
├── README.md
├── requirements.txt
├── package.json              # npm test → ./run_tests.sh
├── setup.sh / setup.cmd
│
├── run_pdf_to_notes.sh       # Main entry point
├── run_md_to_notes.sh
├── run_notes_to_pdf.sh
├── run_tests.sh
├── run_pdf_to_xmind.sh       # Legacy mind-map runners
├── run_md_to_xmind.sh
├── run_opml_to_xmind.sh
│
├── prompts/
│   ├── prompt-rewrite-notes.md   # Default lecture notes prompt
│   └── prompt-mind-map.md          # OPML mind-map prompt
│
├── scripts/                  # Python automation (see table above)
├── inputs/                   # Default input folder
├── outputs/                  # Generated notes & PDFs (gitignored)
├── logs/                     # Batch summaries (gitignored)
├── chrome_profile/           # Browser session (gitignored)
└── tests/
    ├── test_download_detection.py
    └── test_convert_md_to_pdf.py
```

---

## Testing

```bash
./run_tests.sh
# or
npm test
```

**16 tests** covering:
- ChatGPT download link / OPML / Markdown artifact detection
- PDF metadata stripping, RTL detection, preset application
- Rich index auto-discovery
- WeasyPrint end-to-end smoke test

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| Browser not found | Install Chrome/Chromium; check `PATH` |
| Not logged in | Log in manually when browser opens |
| No file downloaded | Run with `--save-diagnostics`; inspect `downloads/` and `logs/` |
| `Could not load temporary chat` | Cookie pile-up: `python3 scripts/prune_chatgpt_cookies.py` |
| Browser restarts every file | Use one batch run; retries reset chat only, not browser |
| Wrong ChatGPT model | Pass `--model "GPT-4o"` |
| PDF import error | `pip install weasyprint markdown pypdf` |
| Combined PDF missing rich index | Ensure `STUDY_INDEX-rewritten.md` exists; set `INDEX_MD` |
| `STUDY_INDEX` inside combined body | Update to latest code — topic filter excludes meta files |
| XMind won't open | Re-run `./run_opml_to_xmind.sh` on existing OPML |
| WeasyPrint font issues (Persian) | Install `fonts-vazirmatn` or `fonts-noto` system packages |
| WeasyPrint `cairo` / `pango` errors | Install packages from [WeasyPrint on Linux](#installation) |
| `ModuleNotFoundError: yaml` | `pip install pyyaml` or re-run `./setup.sh` |
| Batch skips some input files | Files named `00_INDEX*`, `INDEX`, or `README` are excluded by design |
| Notes lack `pdf_pages` after enrich | Filenames in `ORIGINAL_PARTS_DIR` must match `NOTES_DIR` exactly |

**Logs:** `logs/last_batch_summary.json` — per-file success/failure after each batch.

**Diagnostics:** Re-run a single failed file with `--limit 1 --save-diagnostics` and inspect `downloads/`, `*.last_response.txt`, and `*.last_state.png` in the output folder.

---

## Legacy mind-map pipeline

Original OPML → XMind workflow (still fully supported):

```bash
./run_pdf_to_xmind.sh --overwrite          # PDF → OPML → XMind
MARKDOWN_FILE=notes.md ./run_md_to_xmind.sh  # Sections → OPML → XMind
./run_opml_to_xmind.sh                       # OPML folder → XMind only
```

Use `prompts/prompt-mind-map.md` for concept-consolidated exam-oriented mind maps.

---

## Portability & privacy

- Copy the project folder anywhere — no hardcoded user paths
- Point `INPUT_DIR`, `NOTES_DIR`, `MARKDOWN_FILE` via environment variables
- `chrome_profile/` holds your ChatGPT session locally (never committed)
- `outputs/`, `logs/`, `downloads/` are gitignored

---

## Related

Forked from the ChatGPT mind-map automation project. Mind-map features remain; lecture-note rewriting and PDF export are the primary focus.

**Repository:** https://github.com/alifazelidehkordi/note-maker