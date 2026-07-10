# ChatGPT Note Maker

[![Version](https://img.shields.io/badge/version-0.8.0-blue)](CHANGELOG.md) [![Tests](https://img.shields.io/badge/tests-169%20passing-brightgreen)](#testing)

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
- [Phase 1 release acceptance](#phase-1-release-acceptance)
- [Upgrading to 0.2.0](#upgrading-to-020)
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
| **Provider-based browser automation** | Selenium remains default; opt-in Patchright adds persistent contexts, typed recovery, and event-first downloads |
| **Managed browser sessions** | Authenticated session snapshots, atomic profile leases, and isolated per-run/per-worker profile, download, log, and diagnostics directories |
| **Structured notes** | Default prompt enforces `# Title` → `## Explanation` → `## Key Points` |
| **Metadata enrichment** | Copy `pdf_pages`, `chapter`, `part` from original split parts into rewritten notes |
| **Rich study index** | Automatically generate `STUDY_INDEX.md` from the current notes with chapters/groups, sessions, page ranges, time, and study-focus columns |
| **Study PDFs** | WeasyPrint export with medical-blue theme, RTL auto-detection, Key Points highlighting |
| **Combined book** | One PDF with a generated front index, clickable internal session links, bookmarks, and all topic notes in order |
| **Mind maps** | Legacy OPML generation + conversion to themed XMind files |
| **Resilient batches** | Versioned manifest, hash-based resume, crash recovery, retries, validation, and automatic diagnostics |
| **Configurable parallel runtime** | Dynamic 1–16 process workers, atomic job claims, heartbeat monitoring, worker replacement, and graceful shutdown |
| **Production resilience controls** | Global rate-limit cooldown, bounded category-specific retries, auth/rate circuits, opt-in adaptive concurrency, worker recycling, and stale-process cleanup |

---

## Requirements

| Dependency | Purpose |
|------------|---------|
| Python 3.10+ | All automation scripts |
| Google Chrome / Chromium | ChatGPT web UI |
| ChatGPT account | Bootstrap one reference login profile, then clone a validated local session snapshot into isolated worker profiles |
| Linux or Windows | `.sh` / `.cmd` runners for both |

**Linux system packages** (PyAutoGUI + browser):

```bash
sudo apt install -y python3-tk python3-dev chromium-browser
```

**Python packages** (`requirements.txt`):

```
selenium  pyautogui  pyperclip  markdown  weasyprint  pypdf  pyyaml
patchright==1.61.2  playwright-stealth==2.0.3
```

`pyyaml` is required for `generate_study_index.py` and `enrich_rewritten_notes.py`. Patchright dependencies are pinned for reproducible browser behavior. Setup reuses a system Chrome/Chromium when available; otherwise it installs Patchright Chromium.

---

## Installation

```bash
git clone https://github.com/alifazelidehkordi/note-maker.git
cd note-maker
chmod +x setup.sh run_*.sh
./setup.sh          # creates .venv-linux, installs deps
```

**Windows:** run `setup.cmd`.

**First authenticated run (recommended):** create a dedicated reference profile and a reusable session snapshot. Close the browser after login so the snapshot can be created safely.

```bash
./run_login.sh --profile chrome_profile_login --snapshot-name default
# Windows: run_login.cmd --profile chrome_profile_login --snapshot-name default
```

The command prints the snapshot id. Use it with `--profile-snapshot` for isolated runs; the original login profile is never shared with a worker.

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
5. Writes `logs/runs/<run-id>/summary.json` and updates the compatible `logs/last_batch_summary.json` copy

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

**Combined PDF integration:** when no custom index is passed, `create_combined_pdf.py` generates a fresh `STUDY_INDEX.md` from the current notes and places it at the beginning of the merged PDF. Session-title links are then rewritten to internal PDF destinations, so clicking a title jumps to the first page of that section inside the same final file. The final book also receives one continuous visible page-number sequence and matching PDF page labels, starting at 1 by default. Existing per-topic footer counters are masked before the final number is stamped. A custom `STUDY_INDEX-rewritten.md` can still be supplied with `--index-md` or `INDEX_MD=...`.

**Topic file filter:** numbered names such as `01_...` and `01_02_...` are naturally sorted; unnumbered Markdown notes are also accepted. Meta files (`STUDY_INDEX-*`, `COMBINED_NOTES`, `README`) are excluded.

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

1. **Browser provider and isolated session** — Selenium remains the default and Patchright is opt-in. Level 3 can restore a validated login snapshot into `.runtime/runs/<run-id>/workers/<worker-id>/profile`; each browser receives independent profile/download paths and an atomic ownership lease. Direct legacy profiles are still supported but are lease-protected.
2. **Temporary chats** — Each input file opens a fresh ChatGPT chat (avoids context bleed between lectures).
3. **Upload & prompt** — The file is attached, then the full text of `PROMPT_FILE` is sent.
4. **Strict, event-first download detection** — Each job declares its expected artifact type. Patchright registers the browser download event before clicking and saves directly into a job-specific staging directory; filesystem scanning is only a bounded fallback. Generic links such as “Download file” or “notes” are ignored unless the expected format is explicit.
5. **Fresh-file tracking** — The pre-run snapshot stores each download path, modification time, and size. New files and same-name browser overwrites are detected, while unchanged or pre-prompt files are ignored.
6. **Validation & atomic save** — Markdown must contain an H1, an H2, meaningful content, and no known assistant-error response. OPML is repaired, parsed, and checked for a body and outline. The previous output is replaced only after validation succeeds.
7. **Manifest and true resume** — Each output directory has a schema-v2 `manifest.json`. Source, prompt, model, output, weight, run/worker metadata, attempts, status, and SHA-256 hashes are recorded atomically. Schema v1 files migrate automatically. A second unchanged run skips valid completed jobs before constructing a browser provider; changed sources/prompts, missing outputs, invalid outputs, failed jobs, and interrupted jobs are rebuilt.
8. **Automatic failure diagnostics** — The final failed retry is always captured under `<output-dir>/diagnostics/<run-id>/<job>/` with `metadata.json`, the last assistant response, and a screenshot. `--save-diagnostics` also preserves intermediate failed retries. Invalid candidates are preserved under `<output-dir>/_rejected/` and copied into validation diagnostics when available.
9. **Privacy-aware page source** — HTML page source is not stored by default. Add `--save-page-source` only when deeper UI debugging is required.
10. **Summary log** — Every run writes `logs/runs/<run-id>/summary.json`; `logs/last_batch_summary.json` remains a compatible latest copy and `last_batch_summary.pointer.json` identifies its immutable source.

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
- Batch conversion reports both created and failed files; any partial failure exits with code `2`
- `run_notes_to_pdf.sh` stops before combined-book generation when an individual PDF fails

### Combined PDF

Before merging, each topic PDF is regenerated when it is missing or older than its Markdown source. Current PDFs are reused.

```bash
python scripts/create_combined_pdf.py \
  --notes-dir outputs/phisiopath-full \
  --pdf-dir outputs/phisiopath-full/pdfs \
  --output outputs/phisiopath-full/COMBINED_NOTES.pdf \
  --title "Physiopathology"
```

Continuous numbering is enabled by default. Use `--page-number-start 1` to choose a different positive starting number, or `--no-continuous-page-numbers` to retain the old component numbering. When `--css`/`CSS_FILE` is supplied, the same custom font CSS is used for the index and the final page-number overlay.

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
| `run_login.sh` / `run_login.cmd` | Open a dedicated reference profile, verify login evidence, and create a reusable authenticated snapshot |
| `run_tests.sh` | Run full unit test suite |

All `run_*.sh` scripts accept forwarded flags (`--overwrite`, `--limit`, `--model`, etc.).

---

## Python scripts reference

| Script | Role |
|--------|------|
| `run_chatgpt_temporary_test.py` | Compatibility facade for the legacy Selenium API |
| `profile_bootstrap.py` | Inspect/login/snapshot/prepare/cleanup CLI for managed browser profiles |
| `smoke_test_profile_isolation.py` | Real two-process Patchright isolation and scoped-cleanup smoke test |
| `batch_pdf.py` | Batch processor for PDF/DOCX/MD inputs |
| `batch_markdown.py` | Split Markdown by `##`, process each section |
| `batch_common.py` | Shared batch utilities: retries, cookies, logging, failure capture |
| `artifact_validation.py` | Structural validation for Markdown and OPML artifacts |
| `diagnostics.py` | Atomic metadata, response, screenshot, and optional page-source capture |
| `manifest.py` | Schema-v2 coordinator-owned job/run state, migration, batched atomic writes, and resume decisions |
| `pipeline.py` | Unified CLI for PDF or Markdown → OPML/MD → XMind chains |
| `convert_md_to_pdf.py` | Markdown → styled study PDF (WeasyPrint) |
| `create_combined_pdf.py` | Rich index + topic PDFs → one merged book |
| `enrich_rewritten_notes.py` | Copy `pdf_pages` metadata from original parts |
| `generate_study_index.py` | Build rich `STUDY_INDEX-rewritten.md` |
| `convert_opml_to_xmind.py` | Single OPML → themed `.xmind` |
| `convert_opml_batch.py` | Batch OPML → XMind |
| `opml_utils.py` | OPML repair and validation |
| `prune_chatgpt_cookies.py` | Fix piled-up `conv_key_*` cookies (keeps login) |
| `browser_runtime/profile_manager.py` | Selective snapshots, leases, active-profile detection, worker layouts, and retention |
| `browser_runtime/session_manager.py` | Lease-aware session bootstrap and managed session lifecycle |
| `browser_runtime/login_bootstrap.py` | Dedicated reference-profile login and snapshot creation |

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

### Browser runtime and session profiles

| Variable | Default | Description |
|----------|---------|-------------|
| `CHATGPT_RUNTIME_DIR` | `.runtime` | Root for per-run/per-worker profiles, downloads, logs, and diagnostics |
| `CHATGPT_PROFILE_TEMPLATE_DIR` | `profile_templates` | Local authenticated snapshot repository |
| `CHATGPT_PROFILE_SNAPSHOT` | — | Snapshot id or path restored for the managed worker |
| `CHATGPT_RUNTIME_RETENTION` | `delete-success-keep-failure` | `delete-success-keep-failure`, `keep-all`, or `delete-all` |
| `CHATGPT_PATCHRIGHT_PROFILE_DIR` | `patchright_profile` | Direct Patchright profile when no managed snapshot is selected |
| `CHATGPT_CHROME_PROFILE_DIR` | `chrome_profile` | Direct Selenium profile when no managed snapshot is selected |
| `CHATGPT_DOWNLOAD_DIR` | `downloads` | Direct-profile download directory |
| `CHATGPT_CHROME_BINARY` | auto-detect | Explicit Chrome/Chromium executable for Patchright |

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
| `BOOK_TITLE` | `Study Notes` | Title used for the generated index and final PDF metadata |

### Paths & artifacts

| Path | Contents |
|------|----------|
| `inputs/` | Default batch input (PDF, DOCX, `.md`) |
| `outputs/notes/` | Default rewritten Markdown output |
| `outputs/pdfs/` | Individual study PDFs (when `DO_PDF=1`) |
| `downloads/` | ChatGPT browser downloads (staging) |
| `logs/runs/<run-id>/summary.json` | Immutable report for one batch run |
| `logs/last_batch_summary.json` | Compatible copy of the latest batch report |
| `<output-dir>/manifest.json` | Versioned Resume state and hashes for every generated job |
| `chrome_profile/` | Persistent Selenium browser session (local only) |
| `patchright_profile/` | Direct persistent Patchright session when snapshots are not used (local only) |
| `chrome_profile_login/` | Dedicated human-login reference profile (local only) |
| `profile_templates/` | Integrity-checked authenticated session snapshots (sensitive, local only) |
| `.runtime/runs/<run>/workers/<worker>/` | Isolated worker profile, downloads, logs, and diagnostics |

---

## CLI reference

### Shared batch flags (passed through shell scripts)

| Flag | Description |
|------|-------------|
| `--overwrite` | Re-generate files that already exist |
| `--limit N` | Process only first N items |
| `--model "GPT-4o"` | ChatGPT model label in UI |
| `--save-diagnostics` | Save diagnostics for every failed retry; final failures are always saved |
| `--save-page-source` | Also save potentially sensitive `page_source.html` for failed attempts |
| `--manifest PATH` | Use a custom manifest instead of `<output-dir>/manifest.json` |
| `--no-resume` | Ignore Resume decisions and run selected jobs again; still record results |
| `--retry-failed` | Run only failed, interrupted, pending, or invalidated manifest jobs |
| `--adopt-existing` | Validate and register untracked existing outputs without opening ChatGPT |
| `--browser-provider {selenium,patchright}` | Select the browser provider. Selenium remains the default; Patchright is opt-in |
| `--parallel-runs N` | Run 1–16 isolated browser worker processes through the shared dynamic Coordinator runtime |
| `--worker-heartbeat-interval SECONDS` | Heartbeat event interval for each worker; default `10` |
| `--worker-timeout SECONDS` | Replace a ready worker after heartbeat silence; default `45` and must exceed the heartbeat interval |
| `--worker-ready-timeout SECONDS` | Maximum startup time before a worker emits `READY`; default `180` and independent from heartbeat timeout |
| `--worker-startup-stagger SECONDS` | Delay between worker process starts; default `1` |
| `--max-worker-restarts N` | Restart budget per logical worker; default `2` |
| `--shutdown-grace-seconds SECONDS` | Grace period before terminate/kill escalation during shutdown; default `10` |
| `--global-rate-limit-cooldown SECONDS` | Pause all new assignments after a worker rate-limit signal; default `180` |
| `--auth-failures-before-abort N` | Open the global authentication circuit after N startup/runtime auth failures; default `2` |
| `--rate-limit-failures-before-abort N` | Open the severe global rate-limit circuit after N events; default `6`; use `0` to disable |
| `--rate-limit-window-seconds SECONDS` | Observation window for adaptive rate pressure; default `300` |
| `--adaptive-concurrency` | Opt in to automatic active-worker scale-down and timed recovery |
| `--adaptive-scale-down-threshold N` | Rate events required before reducing active concurrency by one; default `2` |
| `--adaptive-recovery-seconds SECONDS` | Quiet period before recovering one active worker slot; default `900` |
| `--worker-max-jobs N` | Recycle a worker after N completed jobs; default `20`; use `0` to disable |
| `--worker-memory-limit-mb MB` | Recycle a worker when its process tree exceeds the RSS threshold; default `0` (disabled) |
| `--network-retries N` | Worker-local retry budget for network failures; default `4` |
| `--browser-retries N` | Worker-local retry budget for browser/runtime failures; default `3` |
| `--download-retries N` | Worker-local retry budget for download failures; default `2` |
| `--rate-limit-retries N` | Worker-local retry budget after a rate-limit response; default `2` |
| `--retry-backoff-base SECONDS` | Exponential retry backoff base; default `3` |
| `--retry-backoff-cap SECONDS` | Maximum computed retry backoff; default `24` |
| `--retry-jitter-ratio RATIO` | Deterministic jitter ratio between `0` and `1`; default `0.20` |
| `--runtime-dir PATH` | Override the managed per-run/per-worker runtime root |
| `--profile-snapshot ID_OR_PATH` | Restore the worker profile from a validated authenticated snapshot |
| `--keep-runtime` | Keep successful managed run directories for diagnostics instead of applying the default cleanup policy |
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
├── run_phase1_acceptance.sh / .cmd
├── run_login.sh / run_login.cmd # Dedicated login + session snapshot bootstrap
├── run_pdf_to_xmind.sh       # Legacy mind-map runners
├── run_md_to_xmind.sh
├── run_opml_to_xmind.sh
│
├── prompts/
│   ├── prompt-rewrite-notes.md   # Default lecture notes prompt
│   └── prompt-mind-map.md          # OPML mind-map prompt
│
├── scripts/                  # Python automation (see table above)
│   ├── browser_runtime/      # Contracts, providers, profiles, leases, sessions, selectors, states, downloads
│   ├── parallel_runtime/     # Planner, Coordinator, spawn workers, event bus, claims, and provider executors
│   ├── profile_bootstrap.py  # inspect/login/snapshot/prepare-worker/cleanup-run CLI
│   ├── run_chatgpt_temporary_test.py # Compatibility facade for the former public API
│   ├── smoke_test_patchright.py # Basic and full manual Patchright smoke checks
│   ├── smoke_test_profile_isolation.py # Real two-process worker-profile isolation smoke
│   └── runtime_flags.py      # Provider/profile and configurable process-worker runtime flags
├── docs/adr/                 # Binding architecture decisions for provider/parallel migration
├── docs/baseline/            # Pre-migration test, CLI, API, and checksum baseline
├── inputs/                   # Default input folder
├── outputs/                  # Generated notes & PDFs (gitignored)
├── logs/                     # Batch summaries (gitignored)
├── chrome_profile/           # Selenium session (gitignored)
├── patchright_profile/       # Direct Patchright session (gitignored)
├── chrome_profile_login/     # Dedicated login reference profile (gitignored)
├── profile_templates/        # Authenticated session snapshots (gitignored)
├── .runtime/                 # Per-run/per-worker runtime trees (gitignored)
└── tests/
    ├── fakes/fake_browser_provider.py
    ├── test_browser_runtime_contracts.py
    ├── test_browser_runtime_architecture.py
    ├── test_fake_browser_provider.py
    ├── test_patchright_provider.py
    ├── test_patchright_downloads.py
    ├── test_browser_response_state_machine.py
    ├── test_profile_manager.py
    ├── test_session_bootstrap.py
    ├── test_artifact_validation.py
    ├── test_atomic_artifact_save.py
    ├── test_download_detection.py
    ├── test_diagnostics.py
    ├── test_batch_diagnostics_integration.py
    ├── test_manifest.py
    ├── test_manifest_v2.py
    ├── test_parallel_coordinator.py
    ├── test_job_claims.py
    ├── test_parallel_batch_dispatch.py
    ├── test_resume_integration.py
    ├── test_phase1_acceptance.py
    └── test_convert_md_to_pdf.py
```

---

## Parallel Runtime Resilience — Level 6

PDF and Markdown batches continue to use the single process-based Coordinator introduced in Level 5 for both `--parallel-runs 1` and multi-worker runs. Level 6 adds a Coordinator-owned resilience layer without giving workers write access to the Manifest.

A rate-limit signal from any worker starts a **global cooldown**: running jobs may finish, but no new job is assigned until the cooldown expires. Authentication failures pass through a one-worker startup barrier and a global circuit breaker, preventing a failing account/session from opening several login windows at once. A separate severe rate-limit circuit stops the run after the configured event ceiling.

Worker-local retries now use independent budgets for content, network, browser, download, and rate-limit failures. Network/browser/download/rate retries use capped exponential backoff with deterministic jitter, while provider `retry_after` values take precedence. Authentication errors are never retried locally.

Optional `--adaptive-concurrency` reduces only the number of active dispatch slots when repeated rate-limit events occur; it does not kill healthy in-flight workers. After a configured quiet period, capacity returns one slot at a time. Worker recycling is independent: a worker can be replaced after a maximum number of completed jobs or after its process tree crosses an RSS limit. The replacement receives a new generation-specific runtime/profile and the completed outputs remain Resume-safe.

The Coordinator also recovers stale claims at startup, records known browser descendants before stopping a worker, terminates surviving child processes, and retains claim ownership until process cleanup is complete.

Example:

```bash
./run_pdf_to_notes.sh \
  --browser-provider patchright \
  --profile-snapshot default \
  --parallel-runs 4 \
  --global-rate-limit-cooldown 180 \
  --adaptive-concurrency \
  --adaptive-scale-down-threshold 2 \
  --adaptive-recovery-seconds 900 \
  --worker-max-jobs 20 \
  --network-retries 4 \
  --browser-retries 3 \
  --download-retries 2 \
  --rate-limit-retries 2
```

The deterministic Level 6 acceptance contract covers global assignment pauses, transient-network recovery within bounded retry budgets, authentication startup circuit behavior, adaptive scale-down/recovery, worker recycling without output loss, stale-claim recovery, and cleanup of surviving child processes.

---

## Testing

```bash
./run_tests.sh
# or
npm test
```

**169 tests** covering:
- Global cooldown, authentication and severe-rate circuit breakers, adaptive active-worker limits, and recovery after a quiet window
- Independent content/network/browser/download/rate retry budgets with capped exponential backoff, deterministic jitter, and provider `retry_after` handling
- Worker recycling by completed-job count or process-tree RSS, generation-safe replacement, stale-claim startup recovery, and surviving child-process cleanup
- Level 6 resilience/provider/profile/process runtime flags, 1–16 worker validation, and default preservation
- Spawn-based Coordinator/Worker IPC, dynamic pull scheduling, readiness, typed events, and shared execution path for one or many workers
- Atomic cross-run job claims, token ownership, heartbeats, stale dead-owner reclamation, and duplicate suppression
- Crash/heartbeat-timeout recovery, generation-specific replacement profiles, restart budgets, graceful SIGTERM, and forced-kill Resume
- Two independent coordinators sharing an output directory without duplicate execution or completed-record downgrade
- Browser-free shared file/section planning, stable section materialization, estimated scheduling weights, and zero-runnable-job startup avoidance
- Manifest schema-v1 to schema-v2 migration, coordinator-only writes, process-bound ownership, batched flushes, stale coordinator merge, and per-run summaries
- Selective portable snapshots, auth evidence, checksums, path sanitization, symlink exclusion, and active-profile rejection
- Atomic profile leases, stale local owner recovery, worker isolation, retention, and scoped cleanup
- Lease-aware session bootstrap, startup-failure release, and independent provider path injection
- Patchright persistent-session contract, health, typed error mapping, event-first download, validator integration, and send deduplication
- Deterministic response state-machine and filesystem-salvage behavior
- Browser provider/session contracts, typed failure mapping, Selenium delegation, and facade compatibility
- Fake-provider success, timeout, browser crash, invalid download, and provider-neutral diagnostics
- Static architecture checks preventing raw locator usage in batch orchestration
- Versioned manifest transitions, atomic save/backup, and hash-based Resume decisions
- Browser-free unchanged reruns, source-change invalidation, section-level Resume, and existing-output adoption
- Markdown and OPML structural validation
- Atomic artifact replacement and preservation of rejected candidates
- Expected-extension filtering, stale-download rejection, and same-name overwrite detection
- Latest-assistant-message download priority
- Automatic final-failure diagnostics and per-retry diagnostics mode
- Screenshot failure isolation, validation metadata, and opt-in page source
- Batch-summary links to final diagnostic folders
- PDF metadata stripping, RTL detection, preset application
- Rich index auto-discovery
- WeasyPrint end-to-end smoke test
- Partial batch failures and exit-code propagation
- Missing/stale topic PDF rebuild decisions
- A browser-free release flow covering partial failure, final Diagnostics, `--retry-failed`, unchanged Resume, real PDF rendering, internal links, and bookmarks

---

## Phase 1 release acceptance

Run the deterministic acceptance suite before packaging or after upgrading:

```bash
./run_phase1_acceptance.sh
# Windows: run_phase1_acceptance.cmd
```

It writes `logs/phase1-acceptance.json` and returns:

- `0` when all release checks pass;
- `2` when at least one acceptance check fails.

The suite does not open Chrome or contact ChatGPT. It uses a fake provider for batch/retry/Resume behavior and real WeasyPrint/PyPDF processing for the final book. Keep its artifacts for inspection with:

```bash
./run_phase1_acceptance.sh \
  --workdir /tmp/notemaker-phase1-acceptance \
  --report /tmp/notemaker-phase1-acceptance/report.json
```

See [`docs/PHASE1_ACCEPTANCE_FA.md`](docs/PHASE1_ACCEPTANCE_FA.md) and [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md). A logged-in browser smoke test remains a manual release requirement.

---

## Upgrading to 0.2.0

Back up existing outputs first. Existing files without a Manifest are rebuilt by default; validate and register them once with:

```bash
./run_pdf_to_notes.sh --adopt-existing
```

Then run:

```bash
./run_tests.sh
./run_phase1_acceptance.sh
```

Full migration, Exit Code, Diagnostics, Resume, and rollback guidance is available in [`docs/PHASE1_MIGRATION_FA.md`](docs/PHASE1_MIGRATION_FA.md). Release changes are listed in [`CHANGELOG.md`](CHANGELOG.md).

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| Browser not found | Install Chrome/Chromium; check `PATH`. For Patchright, run `.venv-linux/bin/python -m patchright install chromium` when no system browser is available |
| Not logged in | Run `./run_login.sh --profile chrome_profile_login --snapshot-name default`, close the login browser, then pass the printed id with `--profile-snapshot` |
| Profile is already owned/active | Close every browser using that profile. Do not snapshot or reuse a profile with `Singleton*` markers or a live `.note-maker-profile-owner.json` lease |
| Snapshot checksum mismatch | Treat the snapshot as corrupted or modified; delete it and create a new snapshot from the closed reference profile |
| Successful runtime disappears | This is the default retention policy. Add `--keep-runtime` or set `CHATGPT_RUNTIME_RETENTION=keep-all` for diagnostics |
| No file downloaded | Confirm the assistant produced the requested extension; inspect the automatic path listed in `logs/last_batch_summary.json` |
| Wrong artifact type is present in `downloads/` | It is intentionally ignored; rerun with the correct `--output-ext` or fix the prompt |
| Generated artifact is rejected | Inspect `<output-dir>/_rejected/` and the validation error in `run.log` |
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
| `Patchright is not installed` | Re-run `./setup.sh` or install the pinned dependencies from `requirements.txt` |
| Patchright browser download fails | Set `CHATGPT_CHROME_BINARY` to an installed Chrome/Chromium executable or retry `python -m patchright install chromium` with working network access |
| Batch skips all completed files | This is normal Resume behavior. Inspect `<output-dir>/manifest.json`; use `--overwrite` or `--no-resume` to regenerate. |
| Existing outputs are rebuilt after upgrading | Untracked files are deliberately not trusted. Use `--adopt-existing` once to validate and register them. |
| Only failed jobs should be rerun | Add `--retry-failed`; new and valid completed jobs are filtered out. |
| Batch skips some input files | Files named `00_INDEX*`, `INDEX`, or `README` are excluded by design |
| Notes lack `pdf_pages` after enrich | Filenames in `ORIGINAL_PARTS_DIR` must match `NOTES_DIR` exactly |

**Resume state:** `<output-dir>/manifest.json` — schema-v2 source/prompt/output hashes, estimated weight, run/worker metadata, status, attempts, timestamps, and diagnostic path per job. Schema v1 migrates automatically. A `.bak` copy preserves the previous healthy manifest during updates.

**Logs:** `logs/runs/<run-id>/summary.json` — immutable per-run result; `logs/last_batch_summary.json` is the latest compatible copy.

**Diagnostics:** Final failures are saved automatically under `<output-dir>/diagnostics/<run-id>/<job>/`. Use `--save-diagnostics` to retain intermediate failed retries too. Add `--save-page-source` only when HTML inspection is necessary because it may contain sensitive session data.

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
- `chrome_profile/`, `patchright_profile/`, and `chrome_profile_login/` hold local browser/session data and are never committed
- `profile_templates/` contains authenticated snapshots; treat it as credential-equivalent sensitive data
- `.runtime/` contains disposable per-run/per-worker profile clones and diagnostics
- `outputs/`, `logs/`, `downloads/`, profiles, snapshots, and runtime trees are gitignored
- Snapshot metadata stores only a hashed source fingerprint, not the source profile absolute path; known absolute directory preferences are sanitized

---

## Related

Forked from the ChatGPT mind-map automation project. Mind-map features remain; lecture-note rewriting and PDF export are the primary focus.

**Repository:** https://github.com/alifazelidehkordi/note-maker  
**Grok skill (bundled install):** https://github.com/alifazelidehkordi/chatgpt-note-maker-skill — use `/chatgpt-note-maker` after installing