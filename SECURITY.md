# Security Policy

## Supported versions

Security fixes are applied to the latest release and the current default branch. Older releases may not receive patches.

| Version | Supported |
|---|---|
| Latest release | Yes |
| `main` | Yes |
| Older releases | Best effort |

## Reporting a vulnerability

Please do not publish credentials, browser profiles, cookies, session databases, private documents, generated outputs, screenshots, diagnostics, or exploit details in a public issue.

Use GitHub's **Security → Report a vulnerability** flow for this repository. If private vulnerability reporting is unavailable, open a public issue containing only a request for a private reporting channel; do not include sensitive technical details.

A useful private report includes:

- affected version or commit;
- operating system and browser provider;
- impact and realistic attack scenario;
- minimal reproduction steps;
- relevant sanitized logs or screenshots;
- whether authenticated profile or document data may have been exposed.

## Sensitive local data

Note Maker automates an authenticated browser and can process private source documents. Treat the following as secrets:

- browser profile and snapshot directories;
- cookies, Local Storage, Session Storage, IndexedDB, Login Data, and Web Data;
- runtime directories, diagnostics, screenshots, page source, and logs;
- prompts, uploaded documents, generated notes, manifests, and downloads.

Never attach these artifacts to issues or pull requests without sanitizing them. Before sharing diagnostics, remove account identifiers, document content, URLs containing tokens, cookies, authorization headers, and filesystem paths that reveal personal information.

## Scope expectations

This project drives the ChatGPT web interface through local browser automation. Reports about bypassing third-party service controls, credential theft, session hijacking, unsafe profile handling, cross-job artifact mix-ups, arbitrary file access, command injection, or secret leakage are in scope. Service availability or UI changes without a security impact are reliability issues rather than vulnerabilities.
