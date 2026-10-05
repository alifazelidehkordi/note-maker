# Runtime environment variables

Every supported runtime or command key has a `NOTE_MAKER_` environment form; key names are uppercased. Environment variables override `note-maker.toml`, which overrides built-in defaults (see [configuration precedence](configuration.md#configuration-precision)).

Boolean values accept `true`, `false`, `yes`, `no`, `on`, `off`, `1`, and `0`.

## Core runtime

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `NOTE_MAKER_BROWSER_PROVIDER` | str | `selenium` | `selenium` or `patchright` |
| `NOTE_MAKER_PARALLEL_RUNS` | int | `1` | Worker count |
| `NOTE_MAKER_RUNTIME_DIR` | str | `.runtime` | Managed runtime root |
| `NOTE_MAKER_PROFILE_SNAPSHOT` | str | — | Snapshot ID or `[sessions]` alias |
| `NOTE_MAKER_KEEP_RUNTIME` | bool | `false` | Keep managed run dirs after success |
| `NOTE_MAKER_CONFIG` | str | — | Explicit path to `note-maker.toml` |

## Retries and cooldowns

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `NOTE_MAKER_NETWORK_RETRIES` | int | `4` | Network-failure retry budget |
| `NOTE_MAKER_BROWSER_RETRIES` | int | `3` | Browser-failure retry budget |
| `NOTE_MAKER_DOWNLOAD_RETRIES` | int | `2` | Download-failure retry budget |
| `NOTE_MAKER_RATE_LIMIT_RETRIES` | int | `2` | Rate-limit retry budget |
| `NOTE_MAKER_GLOBAL_RATE_LIMIT_COOLDOWN` | float | `180` | Cooldown seconds after a rate-limit signal |
| `NOTE_MAKER_RETRY_BACKOFF_BASE` | float | `3.0` | Exponential backoff base |
| `NOTE_MAKER_RETRY_BACKOFF_CAP` | float | `24.0` | Exponential backoff cap |

## Workers and adaptive concurrency

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `NOTE_MAKER_WORKER_MAX_JOBS` | int | `20` | Jobs per worker before recycling (0 = never recycle) |
| `NOTE_MAKER_WORKER_MEMORY_LIMIT_MB` | float | `0` | Worker recycle threshold (0 = disabled) |
| `NOTE_MAKER_WORKER_HEARTBEAT_INTERVAL` | float | `10.0` | Heartbeat period |
| `NOTE_MAKER_WORKER_TIMEOUT` | float | `45.0` | Worker startup/liveness timeout |
| `NOTE_MAKER_WORKER_READY_TIMEOUT` | float | `180.0` | Worker readiness timeout |
| `NOTE_MAKER_ADAPTIVE_CONCURRENCY` | bool | `false` | Enable adaptive scale-down/up |
| `NOTE_MAKER_ADAPTIVE_SCALE_DOWN_THRESHOLD` | int | `2` | Failures before scaling down |
| `NOTE_MAKER_ADAPTIVE_RECOVERY_SECONDS` | float | `900.0` | Wait before scaling back up |

## Scheduled rest (0.9.0)

Pause new job admissions after every N completed files. State persists across restarts; see the [README section](../README.md#scheduled-rest) for behavior details.

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `NOTE_MAKER_REST_EVERY` | int | `0` | Pause interval in completed files (0 = disabled) |
| `NOTE_MAKER_REST_SECONDS` | float | `1800.0` | Rest duration in seconds |
| `NOTE_MAKER_REST_STATE` | str | — | Path of the persistent state file (required when `REST_EVERY` > 0) |
| `NOTE_MAKER_REST_BASE_COMPLETED` | int | `0` | Completed count from previous subjects/runs, counted toward the interval |

Example — rest 30 minutes after every 30 files, counting two prior subjects:

```bash
export NOTE_MAKER_REST_EVERY=30
export NOTE_MAKER_REST_SECONDS=1800
export NOTE_MAKER_REST_STATE=logs/rest-state.json
export NOTE_MAKER_REST_BASE_COMPLETED=60
```

The TOML equivalents are `[runtime] rest_every`, `rest_seconds`, `rest_state`, `rest_base_completed`.

## ChatGPT behavior flags

These are provider-level flags consumed directly by the browser runtime (not part of the `note-maker.toml` resolver).

| Variable | Type | Default | Purpose |
|---|---|---|---|
| `CHATGPT_REQUIRED_EFFORT` | str | *(unset)* | Required thinking effort (`low`, `medium`, `high`). Every submission verifies the composer setting, adjusts it if possible, and **fails closed** on mismatch. Unset = no verification. |
| `NOTE_MAKER_INLINE_MARKDOWN` | bool | `0` | Deliver `.md` sources inline in the prompt (BEGIN/END markers) instead of uploading |
| `NOTE_MAKER_INLINE_MAX_CHARS` | int | `50000` | Sources longer than this fall back to the normal upload path |
| `LONG_GENERATION_STOP_SECONDS` | int | `900` | Generation length before the coordinator presses Stop |
| `POST_STOP_GRACE_SECONDS` | int | `60` | Grace period after Stop for a late artifact |
| `RATE_LIMIT_WAIT_SECONDS` | int | `180` | Cooldown used when a rate-limit modal survives the bounded re-check |

Example — a High-effort batch with inline delivery:

```bash
export CHATGPT_REQUIRED_EFFORT=high
export NOTE_MAKER_INLINE_MARKDOWN=1
export NOTE_MAKER_INLINE_MAX_CHARS=50000
note-maker run pdf --profile-snapshot default
```

## Observability

These are not environment variables, but the run outputs they describe are the primary monitoring surface:

- `logs/runs/<run-id>/summary.json` — including `download_fallbacks`, `last_fallback_reason`, `delivery_modes`, `interrupted_at_stage`
- `logs/last_batch_summary.json` — pointer to the most recent summary
- `outputs/**/diagnostics/<run-id>/<job>/` — per-failure metadata, response text, screenshot, and (on screenshot failure) page source

See the [README troubleshooting section](../README.md#troubleshooting) for interpretation guidance.
