# ChatGPT Note Maker

[![Version](https://img.shields.io/badge/version-0.8.1-blue)](CHANGELOG.md) [![Tests](https://img.shields.io/badge/tests-169%20passing-brightgreen)](#testing)

Automate lecture-note workflows with the **ChatGPT web UI**:

```text
PDF / DOCX / Markdown
        ↓
ChatGPT web automation
        ↓
Clean structured Markdown notes
        ↓
Optional study PDFs + rich STUDY_INDEX + combined book
```

Designed for dense university and medical material (validated on a 39-topic pathophysiology corpus), but works with any prompt that makes ChatGPT return a downloadable artifact such as Markdown or OPML.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/alifazelidehkordi/note-maker.git
cd note-maker
chmod +x setup.sh run_*.sh
./setup.sh
```

Windows: run `setup.cmd`.

**Linux PDF prerequisites** (skip if you only need Markdown):

```bash
sudo apt install -y python3-tk python3-dev chromium-browser \
  libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
  libffi-dev shared-mime-info fonts-vazirmatn fonts-noto-core
```

### 2. Create a reusable ChatGPT login snapshot

Log in once in a dedicated reference profile, then close the browser so the snapshot can be created safely.

```bash
./run_login.sh --profile chrome_profile_login --snapshot-name default
# Windows: run_login.cmd --profile chrome_profile_login --snapshot-name default
```

Reuse the snapshot with `--profile-snapshot default`. Workers receive isolated profile clones; the original login profile is never shared.

### 3. Rewrite your first batch

Put PDFs or DOCX files in `inputs/`, then run:

```bash
./run_pdf_to_notes.sh \
  --browser-provider patchright \
  --profile-snapshot default \
  --overwrite
```

Output Markdown files are written to `outputs/notes/`.

### 4. Build study PDFs and a combined book

```bash
NOTES_DIR=outputs/notes \
PDF_DIR=outputs/notes/pdfs \
CREATE_COMBINED=1 \
COMBINED_OUTPUT=outputs/notes/COMBINED_NOTES.pdf \
./run_notes_to_pdf.sh
```

Combined PDFs in **v0.8.1** use one continuous visible page-number sequence across the generated index and all topic PDFs. PDF page labels match the visible numbering.

---

## Features

| Capability | Description |
|---|---|
| Batch rewriting | Process a folder of PDFs/DOCX files or split one long Markdown file by `##` sections |
| ChatGPT web automation | Upload files, send prompts, detect downloadable artifacts, and save validated outputs |
| Browser providers | Selenium is the default; Patchright is available for persistent contexts and event-first downloads |
| Managed sessions | Create authenticated snapshots and restore them into isolated per-run/per-worker browser profiles |
| Structured notes | Default prompt produces `# Title`, `## Explanation`, and `## Key Points` |
| Resume support | Manifest-backed hash resume skips unchanged completed work |
| Validation & diagnostics | Structural checks before replacing outputs; final failures save metadata, response, and screenshot |
| Parallel runtime | Run 1–16 isolated browser workers with dynamic job dispatch |
| Level 6 resilience | Global cooldowns, auth/rate circuits, adaptive concurrency, retry budgets, and worker recycling |
| Study index | Generate `STUDY_INDEX-rewritten.md` with chapters, sessions, page ranges, and study focus |
| PDF export | WeasyPrint themes, presets, RTL detection, and custom CSS |
| Combined books | Merge index and topic PDFs with internal links, bookmarks, and continuous numbering |
| Legacy mind maps | Generate OPML and XMind files from PDFs or Markdown sections |

---

## Requirements

| Dependency | Purpose |
|---|---|
| Python 3.10+ | Automation scripts |
| Google Chrome or Chromium | ChatGPT browser automation |
| ChatGPT account | Required for authenticated web UI runs |
| Linux or Windows | Shell and CMD runners are provided |
| WeasyPrint dependencies | Required only for PDF export |

Python dependencies are installed by `setup.sh` from `requirements.txt`:

```text
selenium  pyautogui  pyperclip  markdown  weasyprint  pypdf  pyyaml
patchright==1.61.2  playwright-stealth==2.0.3
```

---

## Workflows

| You have… | Run this | You get… |
|---|---|---|
| PDFs/DOCX in `inputs/` | `./run_pdf_to_notes.sh --overwrite` | Clean `.md` in `outputs/notes/` |
| One long `.md` with `##` sections | `MARKDOWN_FILE=lecture.md ./run_md_to_notes.sh` | One `.md` per section |
| Clean notes on disk | `./run_notes_to_pdf.sh` | Individual PDFs (+ optional combined book) |
| Original parts + rewritten notes | `ORIGINAL_PARTS_DIR=/path/to/parts ./run_notes_to_pdf.sh` | Notes with `pdf_pages` frontmatter |
| Parts + notes, need study index | Add `GENERATE_RICH_INDEX=1` | `STUDY_INDEX-rewritten.md` |
| Full pipeline | `run_pdf_to_notes.sh` with `DO_PDF=1 CREATE_COMBINED=1 ENRICH_SOURCE=1 GENERATE_RICH_INDEX=1` | Rewrite → enrich → index → PDF → combined |
| OPML mind maps (legacy) | `./run_pdf_to_xmind.sh` | OPML + themed XMind files |

### Full pipeline example

```bash
ORIGINAL_PARTS_DIR=/path/to/original-parts \
NOTES_DIR=outputs/clean-notes \
PDF_DIR=outputs/clean-notes/pdfs \
DO_PDF=1 CREATE_COMBINED=1 ENRICH_SOURCE=1 GENERATE_RICH_INDEX=1 \
./run_pdf_to_notes.sh --overwrite
```

| Step | Script | Output |
|---|---|---|
| 1 | `batch_pdf.py` | Rewritten topic Markdown files |
| 2 | `enrich_rewritten_notes.py` | Notes with copied source metadata |
| 3 | `generate_study_index.py` | `STUDY_INDEX-rewritten.md` |
| 4 | `convert_md_to_pdf.py` | Individual topic PDFs |
| 5 | `create_combined_pdf.py` | Combined study book |

Files named `00_INDEX*`, `INDEX`, or `README` are skipped in batch folders.

### Output note format

The default prompt (`prompts/prompt-rewrite-notes.md`) asks ChatGPT to produce downloadable Markdown:

```markdown
# Main Title

## Explanation
Structured explanation with clear mechanisms and bold key terms.

## Key Points
- High-yield review point
```

The automation expects a downloadable file link — not plain chat text.

---

## Study Index

`generate_study_index.py` creates `STUDY_INDEX-rewritten.md` with overview, chapter index, per-chapter tables, and a quick-reference summary.

Original split parts should carry YAML frontmatter for page metadata:

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

`enrich_rewritten_notes.py` copies `pdf_pages`, `book_pages`, `source`, `chapter`, and `part` when filenames match between `ORIGINAL_PARTS_DIR` and `NOTES_DIR`.

Generate manually:

```bash
python scripts/generate_study_index.py \
  --parts-dir /path/to/original-parts \
  --clean-dir outputs/notes \
  --output outputs/notes/STUDY_INDEX-rewritten.md \
  --title "Course Notes"
```

When merging, `create_combined_pdf.py` places the index at the front and rewrites session titles to internal PDF destinations.

---

## PDF Export

Powered by `scripts/convert_md_to_pdf.py` (WeasyPrint).

| Theme | Style |
|---|---|
| `medical-blue` *(default)* | Blue headings, soft Key Points boxes |
| `ink` | Neutral grayscale, print-friendly |
| `emerald` | Green accent, calm reading |

| Preset | Use case |
|---|---|
| `study` *(default)* | Balanced density for daily review |
| `compact` | More content per page |
| `comfortable` | Larger type and margins |
| `print` | Conservative ink usage |

```bash
# Single file
python scripts/convert_md_to_pdf.py note.md --rtl --preset compact --theme emerald

# Batch folder
python scripts/convert_md_to_pdf.py outputs/notes --batch --output outputs/notes/pdfs

# Custom CSS via shell wrapper
CSS_FILE=~/.obsidian/print.css ./run_notes_to_pdf.sh
```

Strips YAML frontmatter, highlights Key Points/Warnings, auto-detects RTL, and exits with code `2` on partial batch failures.

---

## Combined Study Books

`create_combined_pdf.py` merges the study index and topic PDFs into one book.

```bash
python scripts/create_combined_pdf.py \
  --notes-dir outputs/notes \
  --pdf-dir outputs/notes/pdfs \
  --output outputs/notes/COMBINED_NOTES.pdf \
  --title "Study Notes"
```

### Continuous page numbering (v0.8.1)

By default, combined PDFs receive one continuous visible page-number sequence across the index and all topics. PDF page labels match the visible numbering. Per-topic footer counters are masked before the final number is stamped.

```bash
# Start at page 25
python scripts/create_combined_pdf.py ... --page-number-start 25

# Keep older per-component numbering
python scripts/create_combined_pdf.py ... --no-continuous-page-numbers

# Forward custom CSS to index and page-number overlay
python scripts/create_combined_pdf.py ... --css ~/.obsidian/print.css
```

Meta files (`STUDY_INDEX-*`, `COMBINED_NOTES`, `README`) are excluded from topic selection.

---

## Browser Runtime & Level 6 Resilience

| Provider | Status | Notes |
|---|---|---|
| Selenium | Default | Compatible legacy provider |
| Patchright | Opt-in | Persistent contexts, typed recovery, event-first downloads |

Recommended managed run:

```bash
./run_pdf_to_notes.sh \
  --browser-provider patchright \
  --profile-snapshot default \
  --parallel-runs 2
```

Each worker gets isolated `profile/`, `downloads/`, `logs/`, and `diagnostics/` under `.runtime/runs/<run-id>/workers/<worker-id>/`.

**Level 6 resilience** (v0.8.0) adds Coordinator-owned controls without giving workers manifest write access:

| Control | Description |
|---|---|
| Global rate-limit cooldown | Any worker rate-limit signal pauses new assignments temporarily |
| Auth circuit | Repeated auth failures stop the run instead of opening many failing sessions |
| Severe rate circuit | Too many rate-limit events abort the run |
| Category retry budgets | Separate limits for network, browser, download, and rate-limit failures |
| Adaptive concurrency | Optional scale-down of active worker slots during rate pressure |
| Worker recycling | Replace workers after job-count or RSS thresholds |
| Stale-claim recovery | Reclaim abandoned jobs safely on startup |

Example resilient parallel run:

```bash
./run_pdf_to_notes.sh \
  --browser-provider patchright \
  --profile-snapshot default \
  --parallel-runs 4 \
  --global-rate-limit-cooldown 180 \
  --adaptive-concurrency \
  --worker-max-jobs 20 \
  --network-retries 4 \
  --browser-retries 3 \
  --download-retries 2 \
  --rate-limit-retries 2
```

Start with `--parallel-runs 1` or `2` for first use; scale up once stable.

---

## CLI Reference

### Shared batch flags

| Flag | Description |
|---|---|
| `--overwrite` | Regenerate files that already exist |
| `--limit N` | Process only the first N items |
| `--model "GPT-4o"` | ChatGPT model label in UI |
| `--browser-provider {selenium,patchright}` | Choose browser provider |
| `--profile-snapshot ID_OR_PATH` | Restore worker profile from authenticated snapshot |
| `--parallel-runs N` | Run 1–16 isolated browser workers |
| `--manifest PATH` | Custom manifest path |
| `--no-resume` | Ignore resume decisions |
| `--retry-failed` | Run failed, interrupted, pending, or invalidated jobs |
| `--adopt-existing` | Validate and register existing untracked outputs |
| `--save-diagnostics` | Save diagnostics for every failed retry |
| `--pdf` / `--combined` | Aliases for `DO_PDF=1` / `CREATE_COMBINED=1` |
| `--sections 1,3,5-8` | Markdown mode section filter |

### Resilience flags

| Flag | Default | Description |
|---|---:|---|
| `--global-rate-limit-cooldown SECONDS` | `180` | Pause new assignments after rate-limit signal |
| `--auth-failures-before-abort N` | `2` | Open auth circuit after repeated auth failures |
| `--rate-limit-failures-before-abort N` | `6` | Abort after severe rate-limit pressure; `0` disables |
| `--adaptive-concurrency` | off | Reduce active dispatch slots during repeated rate limits |
| `--adaptive-recovery-seconds SECONDS` | `900` | Quiet period before recovering one worker slot |
| `--worker-max-jobs N` | `20` | Recycle worker after completed jobs; `0` disables |
| `--worker-memory-limit-mb MB` | `0` | Recycle worker after process-tree RSS threshold |
| `--network-retries N` | `4` | Retry budget for network failures |
| `--browser-retries N` | `3` | Retry budget for browser/runtime failures |
| `--download-retries N` | `2` | Retry budget for download failures |
| `--rate-limit-retries N` | `2` | Retry budget after rate-limit responses |

### Combined PDF flags

```text
--page-number-start N          Start visible numbering at N (default: 1)
--no-continuous-page-numbers   Keep per-component numbering
--css FILE                     Custom CSS for index and page-number overlay
--index-md FILE                Supply a custom study index
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `INPUT_DIR` | `inputs` | Source PDFs/DOCX |
| `NOTES_DIR` | `outputs/notes` | Rewritten Markdown output |
| `PROMPT_FILE` | `prompts/prompt-rewrite-notes.md` | ChatGPT prompt |
| `DO_PDF` | `0` | Enable PDF export after rewrite |
| `PDF_DIR` | `NOTES_DIR/pdfs` | Individual PDF output |
| `CREATE_COMBINED` | `0` | Build merged PDF |
| `ENRICH_SOURCE` | `0` | Copy page metadata from original parts |
| `GENERATE_RICH_INDEX` | `0` | Generate `STUDY_INDEX-rewritten.md` |
| `ORIGINAL_PARTS_DIR` | — | Source parts for enrich + index |
| `CSS_FILE` | — | Extra CSS for PDF and combined generation |
| `CHATGPT_PROFILE_SNAPSHOT` | — | Snapshot id or path for managed workers |
| `CHATGPT_RUNTIME_DIR` | `.runtime` | Per-run/per-worker runtime root |

---

## Testing

```bash
./run_tests.sh    # or: npm test
```

**169 tests** covering browser providers, managed profiles, manifest resume, parallel coordination, Level 6 resilience, PDF rendering, combined books, internal links, and release acceptance.

Deterministic release acceptance (no browser, no ChatGPT):

```bash
./run_phase1_acceptance.sh
# Windows: run_phase1_acceptance.cmd
```

Returns `0` on success, `2` on failure. Writes `logs/phase1-acceptance.json`. See [`docs/PHASE1_ACCEPTANCE_FA.md`](docs/PHASE1_ACCEPTANCE_FA.md) and [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Not logged in | Run `./run_login.sh`, close browser, then use `--profile-snapshot default` |
| Profile already owned | Close all browsers using that profile; remove stale `.note-maker-profile-owner.json` |
| No file downloaded | Confirm prompt asks for downloadable file; inspect `logs/last_batch_summary.json` |
| `Could not load temporary chat` | `python3 scripts/prune_chatgpt_cookies.py` |
| Batch skips completed files | Normal resume behavior; use `--overwrite`, `--no-resume`, or `--retry-failed` |
| Existing outputs rebuilt after upgrade | Register once with `./run_pdf_to_notes.sh --adopt-existing` |
| WeasyPrint / font errors | Install Linux PDF packages and `fonts-vazirmatn` or `fonts-noto-core` |
| Combined PDF missing index | Generate `STUDY_INDEX-rewritten.md` or set `INDEX_MD=...` |
| Notes lack `pdf_pages` | Filenames must match exactly between `ORIGINAL_PARTS_DIR` and `NOTES_DIR` |

**Resume state:** `<output-dir>/manifest.json` — schema-v2 hashes, status, attempts, and diagnostic paths.

**Diagnostics:** Final failures saved under `<output-dir>/diagnostics/<run-id>/<job>/`. Use `--save-page-source` only when needed — HTML may contain sensitive session data.

---

## Portability & Privacy

- Copy the project folder anywhere; set paths via environment variables.
- `chrome_profile/`, `patchright_profile/`, `chrome_profile_login/`, `profile_templates/`, and `.runtime/` are local, sensitive, and gitignored.
- Treat `profile_templates/` as credential-equivalent (authenticated snapshots).

---

## Related

**Repository:** https://github.com/alifazelidehkordi/note-maker

**Grok skill:** https://github.com/alifazelidehkordi/chatgpt-note-maker-skill — use `/chatgpt-note-maker` after installing

Forked from the ChatGPT mind-map automation project. Lecture-note rewriting and PDF export are the primary focus; mind-map features remain supported.