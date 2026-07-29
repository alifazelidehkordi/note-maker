# Unified configuration and CLI

Note Maker provides one supported command surface while preserving the existing shell and Python entry points.

```bash
note-maker --help
note-maker doctor
note-maker run pdf --dry-run
```

## Installation

The standard setup scripts install the pinned runtime dependency lock. For a development checkout:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
note-maker --version
```

`requirements.lock` contains the exact runtime environment. `requirements-dev.lock` adds the pinned lint, typing, coverage, build, and audit tools.

## Configuration precedence

Settings are applied in this order, with later sources overriding earlier ones:

1. Safe built-in defaults.
2. The `[runtime]` table and selected command table in `note-maker.toml`.
3. A named profile selected with `--profile`.
4. `NOTE_MAKER_*` environment variables.
5. Explicit command-line options and repeated `--set KEY=VALUE` overrides.

Relative paths in a TOML file are resolved from that file's directory. This makes a configuration portable when invoked from another working directory.

The default discovery order is:

1. `--config /path/to/file.toml`
2. `NOTE_MAKER_CONFIG=/path/to/file.toml`
3. `note-maker.toml` in the current directory
4. Built-in defaults

Start from [`note-maker.example.toml`](../note-maker.example.toml).

## Named profiles

```toml
[runtime]
browser_provider = "selenium"
parallel_runs = 1

[commands.pdf]
input_dir = "inputs"
output_dir = "outputs/opml"
prompt = "prompts/prompt-mind-map.md"

[profiles.conservative.runtime]
browser_provider = "patchright"
parallel_runs = 1
adaptive_concurrency = false

[profiles.fast.runtime]
browser_provider = "patchright"
parallel_runs = 4
adaptive_concurrency = true

[profiles.fast.commands.pdf]
save_diagnostics = true
```

Inspect the final values without opening a browser:

```bash
note-maker --config note-maker.toml --profile fast config pdf --json
note-maker --config note-maker.toml --profile fast run pdf --dry-run
```

## Environment overrides

Every supported runtime or command key has a `NOTE_MAKER_` environment form. Key names are uppercased.

```bash
export NOTE_MAKER_BROWSER_PROVIDER=patchright
export NOTE_MAKER_PARALLEL_RUNS=2
export NOTE_MAKER_OUTPUT_DIR=outputs/notes
```

Boolean values accept `true`, `false`, `yes`, `no`, `on`, `off`, `1`, and `0`.

## Commands

### Diagnose the environment

```bash
note-maker doctor
note-maker --json doctor
note-maker doctor --strict
```

The doctor checks Python, required modules, configuration parsing, and browser availability. A bundled Patchright browser can satisfy the browser requirement unless `--strict` is used.

### Process a directory

```bash
note-maker --profile conservative run pdf \
  --input-dir inputs \
  --output-dir outputs/notes \
  --output-ext md
```

The command delegates to the existing PDF/DOCX/Markdown batch runtime, including Manifest, Resume, retries, diagnostics, parallel workers, and browser-provider behavior.

### Process Markdown sections

```bash
note-maker run markdown \
  --markdown-file lecture.md \
  --sections 1-5 \
  --output-ext md
```

`markdown_file` must be supplied by TOML, environment, or command line.

### Validate artifacts

```bash
note-maker validate outputs/notes/topic.md
note-maker --json validate outputs/notes/*.md
```

A failing validation exits with status `2`.

### Show latest status

```bash
note-maker status
note-maker --json status --summary logs/last_batch_summary.json
```

## Generic overrides

`--set` exposes advanced settings without adding a dedicated shortcut for every runtime field. Values use JSON syntax when possible.

```bash
note-maker run pdf \
  --set worker_timeout=180 \
  --set retry_jitter_ratio=0.1 \
  --set adaptive_concurrency=true \
  --dry-run
```

Unknown or invalid runtime values fail through the same central validation used by the existing script entry points.

## Compatibility

The shell launchers and direct modules remain supported. The unified CLI is an orchestration layer over those proven implementations, not a second browser automation engine.
