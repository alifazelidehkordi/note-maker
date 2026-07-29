## What changed

<!-- Describe the behavior change and the user/developer impact. -->

## Why

<!-- Explain the problem, root cause, or decision this addresses. -->

## Validation

- [ ] `python -m compileall -q note_maker scripts tests`
- [ ] `python -m unittest discover -s tests -v`
- [ ] `python -m ruff check note_maker`
- [ ] `python -m mypy note_maker`
- [ ] Relevant acceptance or smoke test completed

## Safety and privacy

- [ ] No browser profile, cookie, credential, source document, generated output, or sensitive diagnostic is included.
- [ ] Download selection, retry behavior, manifest ownership, and Resume invariants remain fail-closed.
- [ ] New configuration values have validation, documentation, and a safe default.

## Release impact

- [ ] No release note needed
- [ ] Changelog updated
- [ ] Version or dependency lock updated
