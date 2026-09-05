# Unified configuration and CLI

Note Maker provides one supported command surface while preserving the existing shell and Python entry points as compatibility launchers.

The supported interactive environment is Python 3.10 or newer with the project installed so the `note-maker` console command is available:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
note-maker --version
```

Use `note-maker` for new workflows. Existing `run_*.sh`, `run_*.cmd`, and direct Python helper entry points remain supported for compatibility, but project setup no longer requires knowing those helper scripts.

## Start a reusable project

Create `note-maker.toml` with reusable input, output, prompt, format, browser-provider, and worker settings:

```bash
note-maker init \
  --input-dir "/home/ali/Desktop/anatomy/Multi-Notes (1)" \
  --output-dir /home/ali/Desktop/anatomy/outputs \
  --prompt /home/ali/Desktop/anatomy/prompt \
  --format md \
  --browser-provider patchright \
  --workers 2
```

`note-maker init` uses the existing `note-maker.toml` configuration model. It refuses to replace an existing file unless `--force` is supplied. Relative paths are saved portably and resolved from the configuration file directory.

Then create a reusable browser session:

```bash
note-maker login --name anatomy
note-maker profiles list
note-maker profiles inspect anatomy
```

`login` opens a dedicated Chromium profile, waits for that browser to close, creates an immutable reusable snapshot with the existing profile service, and stores only the human alias to snapshot-ID mapping in `[sessions]`. Browser credentials and cookies are never written to project configuration.

Cookie markers reported by `profiles inspect` or `doctor` are local evidence that authentication data may exist. They are **not proof that the server currently accepts the session**.

Run with the existing snapshot option using the human alias:

```bash
note-maker run pdf --profile-snapshot anatomy
note-maker status --watch
```

The friendlier `--session` run alias is intentionally not introduced here; existing CLI forms remain stable during the compatibility migration.

## Configuration presets versus browser sessions

These are intentionally different concepts:

- Global `--profile NAME` selects a **configuration preset** from `[profiles.NAME]`.
- `note-maker login --name NAME` creates or updates a **browser session alias** under `[sessions]`.
- `--profile-snapshot NAME` accepts either a session alias from `[sessions]` or an immutable snapshot ID/path.

Example:

```toml
[runtime]
browser_provider = "selenium"
parallel_runs = 1

[commands.pdf]
input_dir = "inputs"
output_dir = "outputs/opml"
prompt = "prompts/prompt-mind-map.md"

[sessions]
anatomy = "anatomy-20260905T120000Z-a1b2c3d4"

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

The `[sessions]` values are references only. They must never contain credentials or cookie material.

## Configuration precedence

Settings are applied in this order, with later sources overriding earlier ones:

1. Safe built-in defaults.
2. The `[runtime]` table and selected command table in `note-maker.toml`.
3. A named configuration preset selected with global `--profile`.
4. `NOTE_MAKER_*` environment variables.
5. Explicit command-line options and repeated `--set KEY=VALUE` overrides.

After those layers are resolved, a `profile_snapshot` value matching a `[sessions]` alias is translated to that alias's immutable snapshot ID. This does not create a second configuration precedence system.

Relative paths in a TOML file are resolved from that file's directory. This makes a configuration portable when invoked from another working directory.

The default discovery order is:

1. `--config /path/to/file.toml`
2. `NOTE_MAKER_CONFIG=/path/to/file.toml`
3. `note-maker.toml` in the current directory
4. Built-in defaults

Start from [`note-maker.example.toml`](../note-maker.example.toml) or generate a project file with `note-maker init`.

## Inspect resolved configuration

Use `config` when you only want to inspect the merged settings and precedence result:

```bash
note-maker --config note-maker.toml --profile fast config pdf --json
```

## Preview the real execution plan

`run ... --dry-run` now goes beyond configuration display. It performs the same browser-free source discovery and manifest planning used immediately before a real run, then reports every candidate as `run`, `skip`, or `adopt` with the planner reason.

```bash
note-maker run pdf --dry-run
note-maker run markdown --sections 1-5 --dry-run
```

The JSON output keeps the existing resolved `values` payload and adds `preview`, including selected sources, output paths, current manifest decisions, estimated scheduling weight, provider, worker count, and snapshot reference.

Preview is read-only: it does not open a browser, create the output directory, write or migrate a manifest on disk, create job claims, create a managed runtime, or materialize Markdown `_md_sections` files. An existing manifest may be read and validated to reproduce the real resume decision.

### Select PDF/DOCX/Markdown input files

For the directory-based `run pdf` workflow, repeat `--include` and `--exclude` to select top-level filenames before planning or execution:

```bash
note-maker run pdf \
  --include "Chapter *.pdf" \
  --include "Lab *.docx" \
  --exclude "*draft*" \
  --dry-run
```

Then remove `--dry-run` to execute the same filtered collection:

```bash
note-maker run pdf \
  --include "Chapter *.pdf" \
  --include "Lab *.docx" \
  --exclude "*draft*"
```

Selection rules are deterministic:

1. The existing collector first finds supported top-level `.pdf`, `.docx`, and `.md` inputs and keeps its built-in index/README exclusions.
2. Repeated `--include` patterns are ORed. With no include pattern, all collected files remain eligible.
3. Repeated `--exclude` patterns are applied after includes and always win.
4. `--limit` is applied after include/exclude filtering.
5. Patterns match the filename only and are case-sensitive on Linux and Windows. Quote shell globs so the shell does not expand them first.

An exact filename is also a valid pattern, for example `--include "Unit 01.pdf"`.

Markdown-section runs continue to use the existing `--sections` selector; `--include` and `--exclude` are intentionally limited to `run pdf`.

## Environment overrides

Every supported runtime or command key has a `NOTE_MAKER_` environment form. Key names are uppercased.

```bash
export NOTE_MAKER_BROWSER_PROVIDER=patchright
export NOTE_MAKER_PARALLEL_RUNS=2
export NOTE_MAKER_OUTPUT_DIR=outputs/notes
```

Boolean values accept `true`, `false`, `yes`, `no`, `on`, `off`, `1`, and `0`.

## Diagnose the selected workflow

```bash
note-maker doctor --target pdf
note-maker --json doctor --target pdf
note-maker doctor --target markdown --strict
```

`doctor` resolves the selected workflow and reports the relevant provider dependencies, resolved input/prompt/output paths, output writability, browser availability evidence, and configured snapshot/session availability. It does not launch a browser or make a live authenticated request, so it reports that limitation explicitly.

## Process a directory

```bash
note-maker --profile conservative run pdf \
  --input-dir inputs \
  --output-dir outputs/notes \
  --output-ext md
```

The command delegates to the existing PDF/DOCX/Markdown batch runtime, including Manifest, Resume, retries, diagnostics, parallel workers, and browser-provider behavior.

## Process Markdown sections

```bash
note-maker run markdown \
  --markdown-file lecture.md \
  --sections 1-5 \
  --output-ext md
```

`markdown_file` must be supplied by TOML, environment, or command line.

## Validate artifacts

```bash
note-maker validate outputs/notes/topic.md
note-maker --json validate outputs/notes/*.md
```

A failing validation exits with status `2`.

## Show latest status

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

Unknown or invalid runtime values fail through the same central validation used by the existing script entry points. With `--dry-run`, those resolved values feed the read-only real planner preview.

## Compatibility

The shell launchers and direct modules remain supported. The installed `note-maker` console command adds project-oriented preview and selection around the existing configuration resolver, planner, browser runtime, profile manager, and batch implementations; it does not introduce a second planner, manifest, browser automation engine, or credential system.
