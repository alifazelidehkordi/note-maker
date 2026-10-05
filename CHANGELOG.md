# Changelog

All notable changes to Note Maker are documented here.

## [Unreleased]

### Added

- Current-UI selector registry: assistant-message detection covers the new
  markdown-text-style container alongside the legacy one for both browser
  providers, with double-counting protection; new composer attach-menu
  selectors and sanitized HTML fixtures with provenance.
- Thinking-effort verification: `CHATGPT_REQUIRED_EFFORT` verifies the
  composer's reasoning effort before every submission, adjusts it via the
  slider with steps computed from the reported level, and fails closed on
  mismatch.
- Inline Markdown delivery: `NOTE_MAKER_INLINE_MARKDOWN=1` sends `.md`
  sources in the prompt (BEGIN/END markers) instead of uploading, with a
  `NOTE_MAKER_INLINE_MAX_CHARS` fallback (default 50,000) and prompt hashes
  computed on the original prompt so resume matching is delivery-mode
  independent.
- Scheduled rest: `rest_every`/`rest_seconds`/`rest_state`/`rest_base_completed`
  in `[runtime]` (env `NOTE_MAKER_REST_*`) pause new admissions after every N
  completed files; state persists across restarts.
- Bounded rate-limit re-check: transient modals are dismissed and the wait
  continues; `RateLimitError` is raised only when dismissal fails or three
  consecutive rate-limited observations occur. Download failures check for a
  visible rate-limit modal before being classified as download errors.
- Run observability: `summary.json` now records `download_fallbacks`,
  `last_fallback_reason`, per-job `delivery_modes`, and
  `interrupted_at_stage`.
- Doctor batch-config preflight: rest-schedule validity (including state-file
  writability), required-effort flag, and inline-delivery settings.
- Diagnostics resilience: when the screenshot capture fails, the page source
  is captured automatically so failures stay debuggable.
- `docs/runtime-variables.md`: complete `NOTE_MAKER_*` reference.

### Fixed

- Redesigned composer uploads: the two-step attach menu is driven explicitly
  (`expect_file_chooser`), photo-only accept lists are no longer treated as
  document-input fallbacks, and the image-token set was extended (avif, bmp,
  heic, heif).
- `compat.py` now resolves the packaged `scripts/` directory
  namespace-package safely; running the CLI from a checkout where `scripts`
  lacks `__init__.py` no longer crashes with `TypeError`.
- Rate-limit modals visible during download attempts are no longer
  misclassified as download failures.
- Deterministic per-slot queue cleanup on every coordinator shutdown path.
- Integrated conservative profile ownership and scoped cleanup, stage events,
  live status snapshots, persistent event journals, structured worker logs,
  and detailed run summaries.
- Integrated project initialization, browser session aliases, provider-aware
  diagnostics, read-only execution previews, filename selection, and the
  interactive CLI. Setup scripts now install the console entry point.
- Combined competing console entry points so detailed status and execution
  previews coexist with interactive and legacy workflows.
- Fixed strict typing and formatting errors in the integrated CLI modules.
- Invalid Markdown section selectors and unreadable/non-UTF-8 preview inputs
  now produce usage errors instead of uncaught exceptions.
- Documented Chromium installation for the manual Patchright setup path.


### Maintenance

- Merged the reviewed checkout, setup-python, and upload-artifact v7 updates.
- Preserved the existing single-file PDF converter and combined-book pipeline;
  did not replace them with obsolete branch implementations.
- See [integration report](docs/INTEGRATION_REPORT_FA.md) for branch decisions,
  conflict resolutions, validation, and environment limitations.

## [0.8.2] — 2026-07-29

### Fixed

- Persistent ChatGPT rate-limit dialogs now raise a typed `RateLimitError` when acknowledgement fails, ensuring the global cooldown and retry policy activate instead of degrading into generic send or response timeouts.
- Context-free generic controls such as `Download`, `Copy`, `Share`, and `Coding Citation` are no longer accepted as artifact triggers merely because the surrounding assistant response mentions Markdown or OPML.
- Distinct rate-limit incidents from the same job now receive unique incident-scoped keys, while duplicate signaling from one failure path is suppressed.
- Patchright and the Selenium compatibility facade now share the same strict artifact-trigger policy.

### Security and release

- Added `SECURITY.md` with private reporting guidance and a sensitive-local-data handling policy.
- Replaced the version-specific release checklist with a reusable checklist covering rate-limit escalation, artifact identity, process hygiene, archive privacy, and independent review.
- Corrected the README license section to match the repository's MIT license and made version/test badges resistant to documentation drift.
- Synchronized `VERSION` and `package.json` at `0.8.2`.

### Verification

- Added regression coverage for persistent rate-limit dialogs, ambiguous download controls, and distinct rate-limit incidents within one job.
- The cross-platform Phase 1 CI matrix and browser-free release acceptance remain required before tagging `v0.8.2`.

## [0.8.1] — 2026-07-10

### Fixed

- Combined PDFs now receive one continuous visible page-number sequence across the index and every topic PDF.
- PDF page labels now match the visible numbering, so viewer page navigation also runs continuously.
- Existing per-topic footer counters are masked before the final book-wide number is stamped.
- Custom CSS is forwarded to combined-book generation, allowing the supplied font family to be used by the index and page-number overlay.
- Internal index links, named destinations, and outlines are preserved after numbering.

### CLI

- Added `--page-number-start` and `--no-continuous-page-numbers` to `create_combined_pdf.py`.
- Added `--css` forwarding to combined generation in all PDF-producing shell workflows.

### Verification

- Added regression tests for visible continuous numbering, page labels, invalid start values, and combined-link preservation.

## [0.8.0] — 2026-07-10

### Level 6: Resilience, Rate Limit, and Adaptive Control

#### Added

- Coordinator-owned `GlobalRuntimeController` for global assignment cooldown, authentication circuit breaking, severe rate-limit circuit breaking, and opt-in adaptive concurrency.
- Worker-local `RetryBudgetPolicy` and `RetryTracker` with independent content, network, browser, download, and rate-limit ceilings.
- Capped exponential retry backoff with deterministic jitter and provider `retry_after` precedence.
- One-worker authentication startup barrier so a broken or expired session cannot open several login windows concurrently.
- Worker recycling after a configurable completed-job count or process-tree RSS threshold, using a new generation-specific runtime/profile.
- Linux process-tree inspection and surviving child/browser cleanup after worker termination.
- Startup stale-claim recovery and run-scoped claim release.
- Typed retry, cooldown, and authentication events plus resilience metrics in PDF/Markdown run summaries.
- Dedicated Level 6 deterministic acceptance runner and process-hygiene tests.

#### Changed

- A rate-limit event pauses all new Coordinator assignments while allowing already running jobs to complete.
- Authentication failures are non-retryable inside workers and are promoted to the global circuit.
- Network, browser, download, and rate-limit failures no longer consume one shared retry counter.
- Adaptive concurrency changes active dispatch capacity without terminating healthy in-flight workers, and restores capacity one slot at a time after the configured quiet period.
- Worker shutdown records known descendants before terminating the parent and cleans surviving child processes before releasing ownership.
- Global cooldown seconds in summaries represent the unique requested cooldown extension rather than elapsed run time.

#### CLI

- Added `--global-rate-limit-cooldown`.
- Added `--auth-failures-before-abort` and `--rate-limit-failures-before-abort`.
- Added `--rate-limit-window-seconds`.
- Added `--adaptive-concurrency`, `--adaptive-scale-down-threshold`, and `--adaptive-recovery-seconds`.
- Added `--worker-max-jobs` and `--worker-memory-limit-mb`.
- Added `--network-retries`, `--browser-retries`, `--download-retries`, and `--rate-limit-retries`.
- Added `--retry-backoff-base`, `--retry-backoff-cap`, and `--retry-jitter-ratio`.
- All new options are forwarded consistently through PDF, Markdown, and Pipeline entry points.

#### Safety

- Cooldown and adaptive control remain Coordinator-only; workers cannot change global scheduling state directly.
- Circuit opening stops new dispatch and preserves completed artifacts and Resume state.
- Retry decisions are bounded by category and authentication errors cannot enter a local retry loop.
- Recycling never requeues a successfully completed job and replacement workers use isolated generation-specific profiles.
- Claims remain protected through process cleanup; stale claims are recovered only under the existing safe ownership rules.

#### Verification

- 169 automated regression tests pass.
- 11 dedicated Level 6 resilience acceptance tests pass.
- All three deterministic release acceptance scenarios pass.
- `compileall` succeeds.
- A real headless Patchright persistent-context smoke test is healthy with system Chromium.

## [0.7.0] — 2026-07-10

### Level 5: Parallel Coordinator and Worker Runtime

#### Added

- Serializable `RunConfig` for process-worker execution and provider-specific executor configuration.
- Spawn-safe worker processes with per-worker command queues, a shared typed event queue, readiness signaling, attempt/job lifecycle events, diagnostics events, and heartbeat threads.
- Dynamic pull scheduling ordered by estimated job weight, with workers requesting their next job instead of receiving fixed file ranges.
- Atomic filesystem `ClaimStore` shared by independent runs, including owner tokens, PID/host identity, heartbeat refresh, stale dead-owner recovery, and idempotent release.
- Coordinator liveness monitoring, worker crash/timeout replacement, job requeue, restart budgets, and generation-specific runtime profile ids.
- Graceful `SIGINT`/`SIGTERM` shutdown, forced terminate/kill escalation, interrupted Manifest state, claim cleanup, and Resume support.
- Real PDF and Markdown browser executors that lazily create one long-lived provider session inside each worker process.
- Runtime controls for heartbeat interval, post-ready worker timeout, independent startup readiness timeout, startup stagger, worker restart budget, and shutdown grace.

#### Changed

- `--parallel-runs` now accepts `1` through `16`; normal single-worker runs use the same Coordinator runtime as multi-worker runs.
- PDF and Markdown parent processes plan jobs and coordinate results but do not construct browser providers or sessions.
- Batch summaries now include worker assignments, restart count, externally completed jobs, Coordinator duration, and interruption state.
- Manifest merging preserves a valid completed disk record when a stale planner/coordinator attempts to downgrade the same job to pending or interrupted.
- Worker replacement uses a new profile generation to avoid browser/profile locks left by a crashed process.
- `--keep-browser` is retained only as a single-worker interactive compatibility path and cannot be combined with parallel runs.

#### Safety

- Workers have no writable Manifest dependency; only the Coordinator applies job state transitions.
- Two independent runs targeting one output tree cannot execute the same claimed job concurrently; the Coordinator re-checks completed Manifest state after claim acquisition to close the check-then-claim race.
- Heartbeat persistence is throttled to avoid a disk write for every in-memory heartbeat event.
- Generation-tagged events from a crashed worker are ignored after replacement, and external-claim timeouts cannot overwrite the active owner's Manifest state.
- Shutdown retains each claim until the worker is confirmed stopped, with terminate-to-kill escalation for processes that ignore `SIGTERM`.
- Exhausted worker restart budgets fail the affected job explicitly instead of leaving it running indefinitely.

#### Verification

- 157 automated tests pass, including 4 worker-count subtests.
- 14 dedicated parallel-runtime acceptance tests pass, including dynamic balancing, crash recovery, heartbeat timeout, generation filtering, graceful shutdown, forced-kill Resume, and shared-output duplicate prevention.
- All three deterministic release acceptance scenarios pass.
- `compileall` succeeds.
- A real headless Patchright persistent-context smoke test remains healthy with system Chromium.

## [0.6.0] — 2026-07-10

### Level 4: Job Planner and Single-writer Manifest

#### Added

- Browser-free shared planning for file and Markdown-section jobs through `parallel_runtime`.
- Serializable `ExecutionJob` identities with deterministic `estimated_weight` and metadata.
- Manifest schema version 2 with automatic schema-1 migration, run records, worker/run execution metadata, interrupted-job state, and run completion records.
- Coordinator-only writable manifest handle, read-only planner/worker view, process-bound write guard, short atomic write lock, and dirty-key merge for independent coordinators.
- Batched manifest updates so all initial planning transitions and run metadata flush in one write.
- Immutable per-run summaries under `logs/runs/<run-id>/summary.json`, plus compatible `last_batch_summary.json` and a latest-pointer file.
- Architecture and regression tests for planning boundaries, migration, stale coordinator merge, write ownership, no-browser zero-job runs, and summary paths.

#### Changed

- PDF and Markdown batches delegate job creation and resume decisions to the shared planner.
- Markdown section inputs are materialized before worker startup, giving future processes stable source paths.
- Browser provider construction is deferred until at least one runnable job exists.
- Runtime messages now identify Level 4; values above one remain fail-closed until the process coordinator and worker runtime are available.

#### Safety

- A writable manifest handle cannot be used after crossing a process boundary.
- Worker/planner code receives a read-only manifest surface and cannot call mutation methods.
- Atomic writes retain the prior `.bak`; concurrent coordinators merge distinct dirty job/run records instead of replacing the whole stale snapshot.
- Parallel browser execution is still disabled in this level.

#### Verification

- 139 automated tests pass.
- Three browser-free acceptance scenarios pass.
- `compileall` succeeds.
- A real headless Patchright persistent-context smoke test remains healthy.

## [0.5.0] — 2026-07-10

### Level 3: Profile Manager and Session Bootstrap

#### Added

- Selective, integrity-checked browser-session snapshots for cookies, Local/Session Storage, IndexedDB, Login Data, Web Data, and profile preferences.
- Per-run/per-worker runtime layout with independent profile, download, log, and diagnostics directories.
- Atomic profile ownership leases, active Chromium profile detection, stale local lease recovery, and fail-closed remote ownership.
- `ProfileManager`, `SessionBootstrapper`, managed browser sessions, login bootstrap CLI, and Linux/Windows `run_login` helpers.
- CLI flags `--runtime-dir`, `--profile-snapshot`, and `--keep-runtime` across PDF, Markdown, and pipeline entry points.
- Real two-process Patchright profile-isolation smoke test and deterministic profile/session-management tests.

#### Changed

- Batch browser startup now acquires a profile lease before cookie maintenance and releases it on close or startup failure.
- Patchright and Selenium providers receive explicit worker profile and download directories from the session bootstrap layer.
- Runtime cleanup follows a configurable policy: delete successful runs and retain failed runs by default, with keep-all and delete-all options.
- Session snapshots remove unsafe links and known absolute directory preferences while preserving Chromium-protected Secure Preferences unchanged.

#### Safety

- Active source profiles cannot be snapshotted or deleted.
- Snapshot files are size- and SHA-256-verified before worker restoration.
- One worker runtime can be stopped or deleted without affecting another worker profile.
- Parallel values greater than `1` remain fail-closed until the Job Planner, Coordinator, and single-writer Manifest are implemented.

#### Verification

- 128 automated tests pass.
- Three browser-free acceptance scenarios pass.
- A real Patchright smoke test launched two simultaneous worker browsers in separate processes and verified profile isolation and scoped cleanup.
- Reuse of an actual logged-in ChatGPT account remains a manual smoke test because no user credentials or session data are bundled.

## [0.4.0] — 2026-07-10

### Level 2: Patchright Browser Provider

#### Added

- Opt-in `PatchrightProvider` and `PatchrightBrowserSession` using a persistent Chromium context.
- Central selector registry, explicit browser/response state machines, and provider health/recovery APIs.
- Login, Cloudflare, rate-limit, network, browser-crash, upload, send, response, and download typed failures.
- DOM-first upload, prompt send idempotency guard, bounded navigation recovery, and long-generation stop/grace policy.
- Event-first download capture with job-specific staging directories and filesystem salvage fallback.
- Independent Patchright smoke-test command and deterministic provider/state/download tests.
- Pinned `patchright==1.61.2` and `playwright-stealth==2.0.3` dependencies.

#### Changed

- `--browser-provider patchright` is now accepted by PDF, Markdown, and pipeline CLIs.
- Download requests carry an optional job key so Patchright can isolate artifacts per job.
- Browser sessions expose provider-neutral health and recovery capabilities.
- Setup scripts reuse an installed system Chrome/Chromium when available and otherwise install Patchright Chromium.

#### Safety

- Selenium remains the default provider and the complete compatibility facade is preserved.
- Parallel values greater than `1` remain fail-closed until the coordinator and single-writer manifest exist.
- Patchright imports are lazy, so Selenium-only runs do not require browser startup or a Patchright profile.
- Download candidates must mention the expected artifact format; generic download controls remain rejected.

#### Verification

- 111 automated tests pass.
- Three browser-free acceptance scenarios pass.
- A real headless Patchright persistent-context smoke test passed using system Chromium.
- The full ChatGPT login/upload/send/download smoke test remains manual because it requires a valid user profile and account.

## [0.3.0] — 2026-07-10

### Level 1: Browser Contract and Compatibility Layer

#### Added

- Provider-neutral `browser_runtime` package with typed contracts, request models, and browser error taxonomy.
- `SeleniumProvider` and `SeleniumBrowserSession` adapters around the existing Selenium behavior.
- Reusable deterministic `FakeBrowserProvider` covering success, response timeout, invalid artifact, and browser crash scenarios.
- Contract, delegation, architecture-boundary, facade-compatibility, and fake-provider tests.

#### Changed

- PDF and Markdown batch jobs now use high-level `BrowserSession` operations instead of raw Selenium driver calls.
- Browser creation and recovery now flow through the provider factory.
- Failure diagnostics use provider-neutral screenshot and page-source capabilities.
- `run_chatgpt_temporary_test.py` is now a compatibility facade; the prior implementation is isolated in `browser_runtime/selenium_legacy.py`.

#### Safety

- The complete Phase 0 public function surface remains available through the facade.
- Selenium imports and locator APIs are isolated from batch orchestration.
- Parallel values greater than `1` remain fail-closed until the coordinator and single-writer manifest are implemented.
- The default provider remains Selenium; no live-browser behavior is switched in this level.

## [0.2.1] — 2026-07-10

### Phase 0: Parallel Runtime Foundation

#### Added

- Frozen pre-migration baseline with full unit-test, acceptance, CLI, public-API, and checksum records.
- Five Architecture Decision Records for provider migration, process workers, single-writer manifest, dynamic scheduling, and per-worker profiles.
- Shared runtime feature flags: `--browser-provider selenium` and `--parallel-runs 1`.
- Runtime flag validation tests and propagation through the top-level pipeline.

#### Safety

- Parallel values greater than `1` fail closed until the coordinator and single-writer manifest exist.
- Unknown browser providers are rejected instead of silently falling back to Selenium.
- Default execution remains the existing single-browser Selenium path.

## [0.2.0] — 2026-07-10

### Phase 1: Stability

#### Added

- Versioned `manifest.json` with SHA-256 fingerprints for source, prompt, and output.
- True Resume for PDF/DOCX jobs and individual Markdown sections.
- Recovery of interrupted `running` jobs and targeted `--retry-failed` execution.
- Safe migration option through `--adopt-existing`.
- Shared Markdown and OPML artifact validation.
- Atomic artifact replacement that preserves the previous healthy output.
- Automatic final-failure diagnostics with response text, screenshot, metadata, and rejected candidate.
- Expected-extension-aware download detection and same-name overwrite detection.
- Browser-free Phase 1 release acceptance suite and JSON acceptance report.
- Linux/Windows CI test workflow plus a Linux PDF acceptance job.

#### Changed

- Markdown-to-PDF batch conversion now reports partial failures and exits with code `2`.
- Combined PDF generation rebuilds missing or stale topic PDFs.
- Generic links such as “Download file” are no longer accepted without an expected artifact type.
- A second unchanged batch run finishes without opening a browser.

#### Safety and privacy

- Invalid downloads are retained under `_rejected/` instead of replacing healthy outputs.
- Page source is diagnostic opt-in because it can contain session data.
- Manifest writes are atomic and preserve the previous copy as `manifest.json.bak`.

#### Known limitations

- The release acceptance suite uses a deterministic fake provider; a logged-in live ChatGPT browser smoke test remains a manual release step.
- Stale PDF detection in this release uses modification timestamps. Content/configuration hashes are planned for a later PDF architecture phase.
- The Selenium implementation remains in the existing large module; modular provider extraction belongs to Phase 2.
