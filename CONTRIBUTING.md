# Contributing to ChatGPT Note Maker

Thanks for helping improve the project.

## Development setup

1. Clone the repository.
2. Run `./setup.sh` on Linux/macOS or `setup.cmd` on Windows for the runtime environment.
3. Install the pinned development environment and editable package:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps -e .
```

4. Create a focused branch from `main`.
5. Make the smallest change that solves the problem.
6. Run the relevant tests before opening a pull request.

## Required checks

```bash
python -m compileall -q note_maker scripts tests
python -m unittest discover -s tests -v
python -m ruff check note_maker tests/test_configuration.py tests/test_unified_cli.py
python -m ruff format --check note_maker tests/test_configuration.py tests/test_unified_cli.py
python -m mypy note_maker
python -m coverage run -m unittest discover -s tests -v
python -m coverage report
python -m build
python -m twine check dist/*
python -m pip_audit -r requirements.lock --progress-spinner off
```

The quality workflow also verifies that dependency locks and all version files remain synchronized.

For browser-free release acceptance and Level 6 runtime changes:

```bash
npm run acceptance
npm run acceptance:level6
```

## Dependency changes

Runtime and development requirements are declared in `pyproject.toml`. Regenerate the exact locks deliberately:

```bash
python -m piptools compile pyproject.toml --resolver backtracking --strip-extras --output-file requirements.lock
python -m piptools compile pyproject.toml --extra dev --resolver backtracking --strip-extras --output-file requirements-dev.lock
```

Validate regenerated locks on both Ubuntu and Windows before merging. Do not edit pinned lock entries without updating `pyproject.toml` or documenting why the lock-only change is required.

## Pull-request checklist

- Explain the user-facing problem and the chosen solution.
- Include tests, or state why tests are not needed.
- Update README or command documentation when behavior changes.
- Keep unrelated refactors out of the same pull request.
- Keep `VERSION`, `package.json`, `pyproject.toml`, README, and CHANGELOG aligned for releases.
- Do not commit generated outputs, runtime folders, browser profiles, cookies, credentials, or personal source documents.

## Reporting bugs

Include the operating system, Python version, browser provider, exact command, relevant logs, and a minimal reproducible input when safe to share. Remove cookies, tokens, personal documents, and other sensitive information before posting diagnostics.

## Security

Do not publish authentication material or private documents in issues. Follow [SECURITY.md](SECURITY.md) for private vulnerability reporting.
