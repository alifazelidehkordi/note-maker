# Release Checklist — v0.8.0 Resilience Level 6

## Source and package

- [ ] `VERSION` and `package.json` are both `0.8.0`.
- [ ] README, CHANGELOG, and the [Level 6 implementation report](docs/implementation-reports/implementation-report-level6-fa.md) are current.
- [ ] Final ZIP excludes authenticated snapshots, browser profiles, runtime directories, claims, downloads, logs, outputs, virtual environments, and Python caches.
- [ ] Selenium remains the default provider and Patchright remains opt-in.

## Global control

- [ ] A worker rate-limit event pauses new assignments globally while in-flight work is allowed to finish.
- [ ] Provider `retry_after` can extend, but never shorten, the configured global cooldown.
- [ ] Authentication failures pass through the one-worker startup barrier.
- [ ] Authentication circuit opening prevents additional worker/login startups.
- [ ] The severe rate-limit circuit stops new dispatch at its configured ceiling.
- [ ] Circuit opening preserves completed artifacts and leaves unfinished jobs Resumeable.

## Retry policy

- [ ] Content attempts and network, browser, download, and rate-limit retries use independent budgets.
- [ ] Authentication failures are not retried locally.
- [ ] Exponential backoff is capped and jitter remains inside the configured ratio.
- [ ] Provider `retry_after` takes precedence for rate-limit retries.
- [ ] Exhausted retry budgets produce an explicit final failure rather than an unbounded loop.
- [ ] Retry counts and final categories are included in Coordinator summaries.

## Adaptive concurrency

- [ ] Adaptive concurrency is disabled unless `--adaptive-concurrency` is supplied.
- [ ] Repeated rate events reduce active dispatch capacity by one slot at a time.
- [ ] Healthy in-flight worker processes are not killed during scale-down.
- [ ] A quiet recovery period restores capacity one slot at a time up to the requested worker count.
- [ ] Minimum/final active worker counts and scale events are recorded.

## Recycling and process hygiene

- [ ] `--worker-max-jobs` recycles a worker without losing completed outputs.
- [ ] `--worker-memory-limit-mb` uses process-tree RSS and can be disabled with `0`.
- [ ] Replacements receive a generation-specific runtime/profile.
- [ ] Known child/browser processes are checked after worker termination and surviving descendants are terminated.
- [ ] Claims are retained until process cleanup is complete.
- [ ] Startup stale-claim recovery respects existing token/PID/host safety rules.
- [ ] Run-scoped claims are released during final shutdown.

## CLI and summaries

- [ ] All Level 6 flags are available in PDF, Markdown, and Pipeline CLIs.
- [ ] Defaults match the documented initial policy: cooldown 180s, auth threshold 2, network retries 4, browser retries 3, worker max jobs 20.
- [ ] Invalid negative values and invalid jitter ratios fail closed.
- [ ] Summaries include cooldown, rate/auth event counts, retry counts, recycling, cleanup, adaptive limits, and circuit reason.

## Automated verification

- [ ] `python -m compileall -q scripts tests` succeeds.
- [ ] `./run_tests.sh` reports at least 169 passing tests.
- [ ] `python scripts/level6_acceptance.py` reports 11 passing tests.
- [ ] `./run_phase1_acceptance.sh` passes all three deterministic scenarios.
- [ ] Basic Patchright persistent-context smoke succeeds.
- [ ] Final ZIP is extracted in a new directory and regression/acceptance gates pass there.
- [ ] No authenticated profile, cookies, credentials, private session data, claims, or runtime artifacts are included.

## Manual authenticated verification

- [ ] With a local authenticated snapshot, run a small PDF batch with 2 Patchright workers.
- [ ] Trigger or observe a real account rate limit and confirm no new jobs dispatch during cooldown.
- [ ] Verify an expired snapshot opens at most one login flow and stops through the auth circuit.
- [ ] Run enough small jobs to observe one worker recycle and confirm all downloads remain valid.
- [ ] Select production concurrency conservatively based on account limits and observed latency.

## Sign-off

| Role | Name | Date | Result |
|---|---|---|---|
| Development |  |  |  |
| Runtime verification |  |  |  |
| Release |  |  |  |
