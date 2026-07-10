# Contributing to ChatGPT Note Maker

Thanks for helping improve the project.

## Development setup

1. Clone the repository.
2. Run `./setup.sh` on Linux/macOS or `setup.cmd` on Windows.
3. Create a focused branch from `main`.
4. Make the smallest change that solves the problem.
5. Run the relevant tests before opening a pull request.

```bash
npm test
npm run acceptance
```

For Level 6 runtime changes:

```bash
npm run acceptance:level6
```

## Pull-request checklist

- Explain the user-facing problem and the chosen solution.
- Include tests, or state why tests are not needed.
- Update README or command documentation when behavior changes.
- Keep unrelated refactors out of the same pull request.
- Do not commit generated outputs, runtime folders, browser profiles, cookies, credentials, or personal source documents.

## Reporting bugs

Include the operating system, Python version, browser provider, exact command, relevant logs, and a minimal reproducible input when safe to share. Remove cookies, tokens, personal documents, and other sensitive information before posting diagnostics.

## Security

Do not publish authentication material or private documents in issues. For sensitive findings, contact the repository owner privately instead of creating a public issue.
