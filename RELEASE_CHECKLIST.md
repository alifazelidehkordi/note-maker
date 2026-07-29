# Release Checklist

Use this checklist for every release. Replace `<version>` with the value in `VERSION`; do not hard-code a historical release number in this file.

## Source and package

- [ ] `VERSION` and `package.json` contain the same `<version>`.
- [ ] `CHANGELOG.md` contains a dated entry for `<version>`.
- [ ] README badges, installation steps, supported providers, and license text are current.
- [ ] `SECURITY.md` describes the supported versions and private reporting route.
- [ ] The release archive excludes authenticated snapshots, browser profiles, runtime directories, claims, downloads, logs, outputs, virtual environments, diagnostics, cookies, and Python caches.
- [ ] Selenium remains the default provider unless a documented migration explicitly changes it.

## Runtime safety

- [ ] A persistent rate-limit dialog produces a typed `RateLimitError` and requests global cooldown; it never degrades into a generic send/response timeout.
- [ ] Repeated delivery of one rate-limit incident extends cooldown without double counting.
- [ ] Distinct incidents from the same job are counted independently inside the configured observation window.
- [ ] Authentication failures pass through the one-worker startup barrier and open the auth circuit at the configured threshold.
- [ ] Circuit opening stops new dispatch while preserving completed artifacts and resumable job state.
- [ ] Content, network, browser, download, and rate-limit retry budgets remain independent and bounded.

## Download integrity

- [ ] Context-free generic controls such as `Download`, `Copy`, `Share`, and `Coding Citation` are rejected as artifact triggers.
- [ ] A candidate is accepted only when its own label, filename, URL, or preview flow identifies the requested artifact type.
- [ ] Multiple generic controls in one assistant message cannot inherit the artifact type from surrounding text.
- [ ] Downloaded content is validated against the expected extension and structure before completion is recorded.
- [ ] Job-specific staging prevents one worker from claiming another job's artifact.

## Parallel runtime and process hygiene

- [ ] Worker generations use isolated event queues and runtime/profile directories.
- [ ] Worker crash, timeout, and recycling paths preserve claims until process cleanup completes.
- [ ] Known child/browser processes are checked after worker termination and surviving descendants are terminated.
- [ ] Startup stale-claim recovery respects token, PID, host, and age safeguards.
- [ ] Adaptive concurrency changes dispatch capacity without killing healthy in-flight workers.

## Automated verification

- [ ] `python -m compileall -q scripts tests` succeeds.
- [ ] `./run_tests.sh` succeeds on supported Python versions and operating systems.
- [ ] `./run_phase1_acceptance.sh` passes all deterministic scenarios.
- [ ] `python scripts/level6_acceptance.py` passes.
- [ ] Focused rate-limit, download-detection, worker-incident, runtime-flag, and session-bootstrap tests pass.
- [ ] A clean extracted release archive passes the same regression and acceptance gates.
- [ ] CI contains no authenticated profile, cookies, credentials, private session data, claims, or generated user documents.

## Manual authenticated verification

- [ ] Run a small PDF and Markdown batch with a local authenticated Patchright snapshot.
- [ ] Confirm a dismissible rate-limit acknowledgement continues safely.
- [ ] Confirm an undismissable or recurring rate-limit dialog pauses new dispatch through global cooldown.
- [ ] Verify an expired snapshot opens at most one login flow and stops through the auth circuit.
- [ ] Verify artifact previews and direct artifact links download the expected file while unrelated generic controls remain untouched.
- [ ] Select production concurrency conservatively based on account limits and observed latency.

## Release artifacts

- [ ] Create the signed tag `v<version>` from the reviewed merge commit.
- [ ] Publish release notes matching `CHANGELOG.md`.
- [ ] Attach checksums for distributed archives.
- [ ] Confirm the repository license and security policy are visible in the release.

## Sign-off

| Role | Name | Date | Result |
|---|---|---|---|
| Development |  |  |  |
| Independent review |  |  |  |
| Runtime verification |  |  |  |
| Release |  |  |  |
