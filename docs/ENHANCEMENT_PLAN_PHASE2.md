# Note Maker Enhancement Plan — Phase 2 (post-critique revision 1)

Committed work on branch `enhancement/real-usage-hardening` (6 commits, all green — 331 tests OK): selector registry (all providers), bounded rate-limit re-check, effort verification, inline Markdown delivery, composer modernization, persistent scheduled rest with unified-config integration.

## Review findings (from the real-life verification round)

**Verified working (8 examples):** config resolution with env>toml>default; `note-maker` CLI entrypoint (help/run/doctor); dry-run plan on a real 3-file project; live rest pacing over 144 global files (rests fire at 30/60/90/120, drain in-flight, persist state); selector parity with the user's proven local implementation; local checkout untouched (8 dirty entries, suite green); resume-safe prompt hashing with inline mode; lint gates.

**Issues found during the round:**

1. **`run` crashes when `scripts` resolves as a namespace package** (`compat.py` `activate_legacy_imports`): `import scripts` yields `__file__ = None` when the package marker (`scripts/__init__.py`) is shadowed — the user's real `note-maker-download-fixed` checkout is in exactly this condition (no `scripts/__init__.py`), and the critic reproduced the exact `TypeError` traceback through that shadowing. Note: a foreign cwd ALONE does not reproduce it (the critic verified rc=0 with plain foreign cwd on the enhancement checkout); the namespace condition is the trigger. **Severity: high.**
2. **Rest boundary walk** initially mis-ported (base-completed offset recorded at the wrong unit); caught by tests, fixed by reverting to the proven global-count-at-call-site semantics. No live impact (fixed pre-commit), but the lesson is recorded.
3. **`doctor` doesn't surface the new config surfaces** — rest/effort/inline flags are invisible to the preflight check, so a misconfigured rest_state path is only discovered mid-batch. **Severity: medium.**
4. **Plan-v2 committed items 7–11 (per `docs/ENHANCEMENT_PLAN.md` numbering) remain unimplemented** (async close bug, semaphore leaks, screenshot diagnostics resilience, download-fallback observability, interruption report) — all measured in real logs (3×/5×/16×/156×/54×). **Severity: medium (they were committed scope).**
5. **Baseline ruff noise**: re-measured 115 pre-existing errors on `scripts/browser_runtime` + `scripts/parallel_runtime` + `scripts/runtime_flags.py`, of which **71 fixable (47 non-hidden `--fix` + 24 hidden/unsafe)**. This phase applies **non-hidden `--fix` only (47)**; unsafe fixes are deferred. Not introduced by this work (phase-1 changes reduced the count). **Severity: low.**
6. **`delivery_mode` is tracked per-session but not surfaced in run summaries.** **Severity: low.**

## Phase-2 plan (one session)

### A. Fix the namespace-package crash (P0)
1. **`activate_legacy_imports` cwd- and shadow-proof resolution** — pinned priority order (critic issue 2): (a) the packaged location: resolve from `note_maker.__file__`'s sibling `scripts/` directory (works for both regular and editable installs via the `note_maker` package itself, which always has a real `__file__`); (b) `importlib.util.find_spec("scripts")` with a real (non-None) `submodule_search_locations` AND a `__file__` — explicitly rejecting namespace specs; (c) last resort: `Path(__file__).resolve().parents[1] / "scripts"`. A decoy `scripts/` directory in the user's cwd must never win — priority (a) is checked first precisely because it does not depend on sys.path search order. Test: decoy `scripts/` dir (no `__init__.py`, no `browser_runtime`) placed in cwd; assert the resolver returns the packaged dir, not the decoy.
2. **Regression test that CAN fail (critic issue 1)**: subprocess reproducing the namespace condition — a `PYTHONPATH`-prepended shadow directory containing a `scripts/` dir WITHOUT `__init__.py` (ahead of the repo on sys.path), running `note_maker.entrypoint run pdf --dry-run` on a temp project. Assert: rc=0, valid plan JSON, and no `TypeError` from `compat.py`. Sanity guard inside the test: assert the shadow condition actually held (`import scripts; scripts.__file__ is None` in the subprocess) — if it didn't, the test FAILS LOUDLY as invalid rather than passing vacuously.

### B. Complete committed-scope items 7–11 (docs/ENHANCEMENT_PLAN.md numbering)
3. **Async close bug** (3× measured): audit the patchright session close path. Note: `close()` currently uses the sync API (`sync_playwright`), so the test does NOT assume the current call site is the offender — it asserts no "was never awaited" RuntimeWarning from ANY coroutine-creation path during a deterministic fake shutdown, using `warnings.catch_warnings(record=True)` (critic-pinned mechanism). If the audit finds no offender, the test still guards the contract; record the audit result.
4. **Semaphore leaks** (5×): deterministic `close()`/`join_thread()` in coordinator shutdown; test asserts the resource_tracker warning is absent after a normal shutdown.
5. **Screenshot diagnostics resilience** (16×): best-effort capture — try/except with page-source fallback, never mask the original error; fake-driver test where screenshot returns False.
6. **Download-fallback observability** (156×): `download_fallbacks` counter + `last_fallback_reason` in `summary.json`; fake-driver test asserts `download_fallbacks: 1` with non-empty reason (critic-pinned acceptance criterion).
7. **Interruption report** (54×): `interrupted_at_stage` + per-worker last-job-state in the summary; test kills a worker mid-job and asserts the stage is recorded.
8. **Surface `delivery_mode` in run summaries** (finding 6): per-job delivery mode flows into the manifest entry; test asserts `delivery_mode` present for both inline and upload paths.

### C. Doctor integration (medium)
9. **`note-maker doctor`** reports: rest config validity (rest_state path writable, rest_every>0 ⟹ rest_state set), effort flag presence, inline flag sanity; `--json` output includes them. Test: doctor on a temp config with a bad rest_state reports the problem and exits non-zero with `--strict`.

### D. Lint hygiene (low, bounded)
10. Apply ruff **non-hidden `--fix` only** to `scripts/browser_runtime` + `scripts/parallel_runtime` + `scripts/runtime_flags.py` (47 of the 115 baseline errors, per the re-measured basis above); unsafe fixes deferred and recorded. No behavior changes — full suite must stay green; if any fix requires semantic changes, skip that rule and record it.

### Out of scope (unchanged)
- Prompt-content changes; touching any local checkout other than reading; CI matrix expansion (deferred follow-up); selenium composer parity (migration target).

### Verification gates
- Full suite green: **331 existing tests + the new tests from this phase (target ≥345 total)** under Python 3.11 in `.venv`.
- The namespace-shadow subprocess test passes AND its sanity guard confirms the shadow condition held (critic issue 1's vacuous-pass risk is closed by construction).
- ruff on all newly-touched files clean; baseline reduced by the documented fixable count, never increased.
- `git status` on `<local working checkout>` unchanged before/after (8 dirty entries).
