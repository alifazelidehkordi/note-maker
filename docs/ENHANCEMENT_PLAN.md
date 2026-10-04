# Note Maker Enhancement Plan — v2 (post-critique)

Working copy: `/home/ali/projects/note-maker-enhancement` (fresh clone of https://github.com/alifazelidehkordi/note-maker @ `16234e8`); implementation branch `enhancement/real-usage-hardening` cut from main HEAD. Baseline verified: full suite green — 302 tests OK, 5 skipped — under Python 3.11 in the copy's `.venv`. Local checkout `~/projects/note-maker-download-fixed` and every other local copy are **read-only** for this work; no prompt-content files are modified.

## Committed scope (one session) vs stretch goals

**Committed:** P0 step 0 + items 1–6, P1 items 7–12. **Stretch (only if all committed items land green with time remaining):** P2 items 13–15. CI-matrix expansion (3.10/3.13/3.14) is a documented follow-up, not committed — the user's real runs execute under the project venv, so this does not block any measured usage path.

## Evidence base (measured, not assumed)

1. **256 real run summaries** across the user's study folders: modes pdf-md 155 / markdown-md 60 / pdf-opml 41; providers **selenium 161, patchright 95** (63% / 37%). 2,507 successful files; success rate pdf-md 95.0%, pdf-opml 94.3%, markdown-md 100%. 54 interrupted runs (9 with failures). 74 rate-limit events; 4 auth failures; 17 stale-claim recoveries; 24 worker recycles. Measured `download_timeout` values: 90 (243 runs), 180 (69), 120 (4).
2. **Real batch log classification**: 156× "download event not emitted → artifact preview/fallback"; 45× download timeouts; 16× screenshot diagnostics failure (`driver returned False`); 7× temporary-chat load recovery; 5× leaked-semaphore warnings; 3× `coroutine 'BrowserContext.close' was never awaited`.
3. **User's own uncommitted fixes** in the working checkout (they had to patch upstream locally to keep batches running): new-UI assistant-message selector union with user-scope exclusion; redesigned composer two-step attach menu + `expect_file_chooser`; `CHATGPT_REQUIRED_EFFORT` fail-closed verification; `NOTE_MAKER_INLINE_MARKDOWN` inline delivery with `start_new_chat` reset; rate-limit modal → `RateLimitError` during wait/download; untracked `rest_schedule.py` persistent admission control.
4. **Divergence check (P0 step 0, already executed)**: `git fetch origin main` + token search of upstream `16234e8` confirmed upstream is missing all 6 local fixes (`NOTE_MAKER_INLINE_MARKDOWN`, `_verify_required_effort`, `data-markdown-text-style='assistant-message'`, "Upload from computer" menu path, `RestSchedule`/`NOTE_MAKER_REST_STATE`, `expect_file_chooser`; `_rate_limit_visible` exists but the wait-loop dismiss-and-continue bug remains). Porting onto a fresh branch from main HEAD is conflict-free by construction.

## P0 — Port the battle-tested local fixes (proven by real usage)

**0. Divergence check — DONE** (see Evidence 4). Recorded so re-runs repeat it before porting.

**1. Assistant-message selector registry — ALL providers.** Replace the single selector in `scripts/browser_runtime/selectors.py` with the union `[data-message-author-role='assistant'], [data-markdown-text-style='assistant-message']:not([data-message-author-role='assistant'] [data-markdown-text-style='assistant-message'])` (user-scope exclusion prevents double counting when new containers nest inside legacy ones). **Selenium coverage (critic issue 1, verified: 3 hardcoded occurrences at `selenium_legacy.py` lines 439, 1127, 1261 and no registry import):** replace all three hardcoded `"[data-message-author-role='assistant']"` strings with the `ASSISTANT_MESSAGE_SELECTOR` registry constant — `find_elements(By.CSS_SELECTOR, ...)` accepts the same comma-union. Update `tests/fakes` to import the registry constant instead of hardcoding (never relax production safeguards to satisfy an old fake). Regression tests: checked-in static HTML fixtures (item 12) asserting legacy markup, new markup, and nested-legacy-in-new are each counted exactly once **through both the patchright locator path and the selenium path** (selenium path via fake driver over the same fixture). Composer/effort/inline items 2/4/5 are intentionally **patchright-only**: the user's real high-volume batches run patchright, selenium is the legacy provider, and selenium composer automation is a documented migration target, not this session's scope.

**2. Composer upload modernization** (`patchright_provider.py`, patchright-only per item 1):
   - two-step attach-menu flow: after clicking attach, look for menu labels ("Upload from computer", "Add photos & files", "Add files", "Upload file") and attach via `expect_file_chooser` — the redesigned composer creates the document input only after menu selection, and setting the pre-existing image-only inputs produces "This file type isn't supported";
   - fix fallback classification: a non-matching accept list is NOT a fallback (it is usually a photo-only control); `is_fallback = not accept or "*/*" in tokens`;
   - extend the image-token set (avif, bmp, heic, heif) so photo-only controls are correctly skipped;
   - add `button[aria-label*='Add files']`, `button[aria-label*='Add photos']` to `ATTACH_BUTTON_SELECTORS`.

**3. Rate-limit correctness — bounded re-check, not unconditional raise (critic issue 4).** In `_await_response`, on `ResponseState.RATE_LIMITED`: dismiss the modal; **if dismissal succeeds and the modal is gone, continue the wait loop with a bounded re-check count (3 consecutive rate-limit states → raise)**; raise `RateLimitError` (message reports "acknowledged" vs "remained visible") only when dismissal fails or the bound is exceeded. Rationale: 74 measured rate-limit events are mostly transient acknowledgements; converting every one into a retry wastes a full attempt and compounds with the rest schedule. Apply the same visible-check guard on the download/preview-fallback exception paths (check `_rate_limit_visible()` before misclassifying as a download failure). Tests: both branches (dismissed-and-continues with bounded count; not-dismissed-raises with `retry_after` preserved).

**4. Effort verification** (`CHATGPT_REQUIRED_EFFORT`, patchright-only): verify trigger `button[data-selected-reasoning-effort]` before EVERY submission. **Step-count computation (critic issue 5):** read the current level from `data-selected-reasoning-effort` first and compute the required ArrowRight count from an explicit ordered map {low: 2, medium: 1, high: 0} over the slider's ordered levels — no assumed fixed two steps; if the current level is unknown/unparsable, attempt the slider steps and rely on the fail-closed post-condition. Post-condition: re-read the attribute; mismatch → `BrowserConfigurationError`, submission blocked. Prevents silently generating a whole batch at Medium when High was required (this actually happened). Tests: medium→high (1 step), low→high (2 steps), already-high (no press), mismatch-after-attempt raises.

**5. Inline Markdown delivery** (`NOTE_MAKER_INLINE_MARKDOWN=1`, patchright-only): read the source .md, wrap with BEGIN/END markers, append to the prompt on send, reset in `start_new_chat`. **Prompt-hash ordering (critic issue 2, verified): the hash must be computed on the original prompt BEFORE appending the inline source** — manifest/resume dedupe keys on prompt hash, so toggling inline mode must not invalidate resume matching. Test asserting the hash is identical with inline mode on and off. **Size guard (critic issue 3):** `NOTE_MAKER_INLINE_MAX_CHARS` (default 50,000) — sources above the threshold fall back to the normal upload path with a log line; test covers the fallback branch. Summary/manifest records `delivery_mode: inline|upload` per job for observability. This bypasses the whole upload path — the fallback of last resort when ChatGPT changes upload UI again.

**6. Scheduled rest** (port local `rest_schedule.py` + coordinator hook): admission-control style — caps `capacity()` using completed + in-flight counts so a two-worker pool does not overshoot the pause boundary; persistent state across restarts; `NOTE_MAKER_REST_BASE_COMPLETED` offset for multi-subject wrappers. **Configuration precedence (critic issue 10): env overrides toml, toml overrides built-in defaults — matching upstream `config.py`'s existing override pattern.** Wire into unified config as `[runtime] rest_every`, `rest_seconds`, `rest_state` and document the precedence. Unit tests: interval trigger, persistence across restart, base offset, both precedence pairs (env>toml, toml>default).

## P1 — Fix measured operational defects (from log classification)

**7. Async close bug** (3× `coroutine 'BrowserContext.close' was never awaited`): audit the patchright provider for sync-context async calls; wrap close in the proper sync API or an `asyncio.run` shim; regression test asserting no un-awaited coroutines on the shutdown path (collect warnings during a fake shutdown).

**8. Semaphore leaks** (5× leaked-semaphore warnings): coordinator/executors create multiprocessing primitives without deterministic cleanup; add explicit `close()`/`join_thread()` in coordinator shutdown; test asserts the resource_tracker warning is absent after a normal shutdown.

**9. Screenshot diagnostics failure** (16× `driver returned False`): the diagnostics screenshot path crashes when the driver is already dead — exactly when diagnostics matter most. Make diagnostics best-effort: try/except around capture with fallback to page-source-only; never mask the original error. Test: fake driver whose screenshot returns False → diagnostics still written with page source, original error preserved.

**10. Download fallback observability** (156× fallback events invisible to summaries): record `download_fallbacks` counter + `last_fallback_reason` in `summary.json`. **Acceptance criterion (critic issue 12): a fake-driver test triggers one fallback and asserts the summary contains `download_fallbacks: 1` with a non-empty `last_fallback_reason`.**

**11. Interruption report** (54 interrupted runs): add `interrupted_at_stage` + per-worker last-job-state to the summary. **Acceptance criterion: a test kills a worker mid-job and asserts `interrupted_at_stage` is set to the observed stage.**

**12. Real-HTML regression fixtures (critic issue 7):** checked-in static HTML fixture files loaded via `page.set_content(...)` — no external browser binary dependency, CI-runnable. Fixture provenance recorded in a header comment inside each fixture: capture date (2026-10), source (user's real ChatGPT session markup), sanitized of all conversation content. Fixtures cover: new assistant container, legacy container, new-nested-in-legacy, two-step attach menu, rate-limit modal.

## P2 — Stretch goals (only if P0+P1 land green)

**13. Python 3.14 CLI fix:** `BooleanOptionalAction` rejects `--no-warm-up`-style names under 3.14 (exposed by fresh-clone testing). Fix the CLI parser or pin `requires-python <3.14` with a documented reason; add 3.13/3.14 to the CI matrix in the same change.
**14. Fresh-clone setup test:** `setup.sh` leaves `typing_extensions` implicit (selenium 4.50 requires it) — the fresh-clone experience failed four different ways before passing. Add a CI job: fresh venv → `setup.sh` → `run_tests.sh` green.
**15. README documentation:** rest-schedule flags, inline-markdown mode, effort verification, and the selector-registry extension point (so the next ChatGPT UI change is a data change in one registry, not a code hunt).

## Out of scope (explicit, with rationale)

- **Download-timeout tuning** (45 measured timeouts): `download_timeout` is already a per-run config knob (default 90; real runs used 90–180); item 10's observability gives the data to tune it later — a default change now would be a guess.
- **Auth-failure handling** (4 events) and **temporary-chat recovery** (7 events): too rare to justify code in the committed budget; existing retry categories already cover them.
- **Selenium composer/effort/inline parity**: documented migration target (see item 1).
- No new features beyond the above; no prompt-content changes (prompt hash is frozen per subject by the user's wrapper); no changes to `~/projects/note-maker-download-fixed` or any other local copy — all work happens on a branch in `/home/ali/projects/note-maker-enhancement`.

## Verification gates (each committed item must pass before "done")

- Full unittest suite green (302 existing + new regression tests) under Python 3.11 in the enhancement copy's `.venv`.
- New regression tests for every P0/P1 item as specified per-item above.
- **Lint/type gates on touched modules (critic issue 6):** `ruff check` + `mypy` on the touched `scripts/browser_runtime` and `scripts/parallel_runtime` files (strict where upstream strictness allows), plus `mypy note_maker` for regression; `compileall` clean.
- Real-diff review: `git diff main --stat` shows only the planned files; no file outside the enhancement copy modified (verified by `git status` on the local checkout before and after).
