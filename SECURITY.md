# Security Policy

## Supported versions

Security fixes are provided for the latest `0.1.x` release line.

## Reporting a vulnerability

Please do not publish credentials, tokens, browser profiles, private research data, or vulnerability details in a public issue.

Send a concise report to **吴永祥 <wu19825306550@163.com>**. Include the affected version, reproduction steps, potential impact, and any suggested mitigation. You should receive an acknowledgement within seven days.

## Credential handling

- Store API keys only in the local `.env` file.
- Local research profiles, runtime databases, Web of Science exports, browser sessions, logs, and generated reports are intentionally excluded from Git.
- The project does not require users to commit credentials to GitHub Actions.
