# Note Maker CLI

The unified `note-maker` CLI supports both guided interactive runs and fully scriptable automation. The interactive workflow is an additional front end to the same configuration resolver and batch-processing functions used by `note-maker run ...`; it does not replace the existing shell/CMD launchers.

## Installation and entry point

The repository setup scripts install the project into the local virtual environment in editable mode, so the console entry point is available after setup.

Linux:

```bash
./setup.sh
.venv-linux/bin/note-maker --help
```

Windows:

```bat
setup.cmd
.venv\Scripts\note-maker.exe --help
```

If the virtual environment is activated, use `note-maker` directly in the examples below.

## Interactive workflow

Start the guided workflow with:

```bash
note-maker interactive
```

The wizard keeps the number of questions deliberately small. It will:

1. ask for an input file or directory, defaulting to the resolved PDF input directory;
2. discover the same top-level PDF, DOCX, and Markdown files used by the existing batch collector;
3. let you select all files or a subset with input such as `1,3-5`;
4. choose the supported workflow automatically, except for a single Markdown file where you may choose between `##` section processing and processing the file as one upload;
5. discover `.md` and `.txt` prompt files from the project/config prompt directories or accept a custom prompt path;
6. choose the output directory and output format;
7. expose the two most important runtime controls: browser provider and parallel worker count;
8. show the fully resolved configuration before execution; and
9. ask for confirmation before starting.

Each discovered source file shows its name and size. The resolved prompt path and output directory are printed explicitly before execution.

To exercise the wizard and review the configuration without opening a browser:

```bash
note-maker interactive --dry-run
```

Use an existing profile with the wizard exactly as with non-interactive commands:

```bash
note-maker --profile conservative interactive
```

Use a non-default configuration file:

```bash
note-maker --config ./configs/course.toml --profile fast interactive
```

### Cancellation

At any wizard prompt, enter `q`, `quit`, or `cancel`, or press Ctrl+C. Normal interactive cancellation exits cleanly with code `130` and does not print a traceback.

The final confirmation defaults to **No**, so pressing Enter at that prompt cancels instead of accidentally starting browser automation.

## Non-interactive usage

The existing flag-based commands remain first-class and are preferred for scripts, CI jobs, and repeatable automation.

Process a directory of PDF, DOCX, or Markdown files:

```bash
note-maker run pdf \
  --input-dir ./inputs \
  --prompt ./prompts/prompt-rewrite-notes.md \
  --output-dir ./outputs/notes \
  --output-ext md
```

Process one Markdown file by level-2 (`##`) sections:

```bash
note-maker run markdown \
  --markdown-file ./inputs/lecture.md \
  --prompt ./prompts/prompt-rewrite-notes.md \
  --output-dir ./outputs/lecture \
  --output-ext md
```

Select specific Markdown sections:

```bash
note-maker run markdown \
  --markdown-file ./inputs/lecture.md \
  --sections 1,3,5-8 \
  --prompt ./prompts/prompt-rewrite-notes.md \
  --output-dir ./outputs/lecture
```

Use runtime options without interactive input:

```bash
note-maker --profile conservative run pdf \
  --input-dir ./inputs \
  --prompt ./prompts/prompt-rewrite-notes.md \
  --output-dir ./outputs/notes \
  --browser-provider patchright \
  --parallel-runs 1
```

Inspect resolution without starting the browser pipeline:

```bash
note-maker run pdf \
  --input-dir ./inputs \
  --prompt ./prompts/prompt-rewrite-notes.md \
  --output-dir ./outputs/notes \
  --dry-run
```

Inspect the resolved configuration and active profile directly:

```bash
note-maker --profile fast config pdf
```

The legacy launchers such as `run_pdf_to_notes.sh`, `run_pdf_batch.sh`, `run_md_to_notes.sh`, and their Windows `.cmd` counterparts remain supported.

## Configuration and profiles

Interactive and non-interactive execution share `note_maker.config.resolve_config`; there is no separate wizard configuration store.

Configuration precedence remains:

1. built-in defaults;
2. `note-maker.toml` command/runtime settings;
3. the selected named profile;
4. `NOTE_MAKER_*` environment variables; and
5. explicit CLI or interactive selections.

Relative paths from a TOML file are resolved relative to that TOML file. Interactive defaults therefore reflect the same resolved profile/configuration values that a normal command would use.

Example profile usage:

```bash
note-maker --config ./note-maker.toml --profile fast interactive
note-maker --config ./note-maker.toml --profile fast run pdf --input-dir ./inputs
```

Advanced settings remain available through normal flags, environment variables, TOML, and repeated `--set KEY=VALUE` overrides rather than being duplicated into a large wizard.

## Input, prompt, and output validation

Before browser execution, the unified CLI checks the common failure cases that can be detected locally:

- the input directory or Markdown file must exist;
- directory batches must contain at least one supported top-level PDF, DOCX, or Markdown file;
- interactively selected files must still satisfy the existing batch inclusion rules;
- the prompt must exist, be readable UTF-8 text, and be non-empty;
- the output path must be a directory path or a creatable path beneath an existing directory; and
- `--keep-browser` cannot be combined with more than one parallel worker.

Errors are reported before browser startup with the relevant path and corrective action where possible.

## Overwrite and resume behavior

The CLI does not introduce new overwrite semantics. The existing defaults and manifest planner remain authoritative:

- `overwrite = false` by default, so outputs are not silently replaced;
- `resume = true` by default, so completed work can be reused according to the manifest;
- `--overwrite` explicitly requests regeneration;
- `--no-resume` disables manifest resume decisions;
- `--retry-failed` retries incomplete/failed work; and
- `--adopt-existing` validates and registers eligible existing outputs.

Interactive file subsets are passed into the existing PDF/DOCX/Markdown-upload batch pipeline through a temporary selection directory. The original source files are not modified, and the normal planner, manifest, validation, retries, browser automation, diagnostics, and output-saving code remain in use.

## Exit codes

The CLI preserves the underlying batch return code. Common CLI-level codes are:

- `0`: successful command or dry run;
- `1`: batch-level failure where the existing processor returns `1`;
- `2`: argument/configuration or artifact-validation failure, depending on the command; and
- `130`: normal interactive/Ctrl+C cancellation.

For the latest batch summary, use:

```bash
note-maker status
```
