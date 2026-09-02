# Contributing to Starling

Thanks for considering a contribution.

## Development Setup

See [Developer Setup](README.md#developer-setup) in the README for cloning, installing dependencies, and running from source.

## Before Opening a PR

- Follow the coding standards in [`.claude/CLAUDE.md`](.claude/CLAUDE.md) — Ruff/PEP 8, double quotes, type hints on all functions, `from __future__ import annotations`, no unused imports.
- Run `uv run ruff check` with zero findings and `uv run pytest -q`.
- Add or update tests for any behaviour change.
- Keep PRs to one feature or fix.
- **Never include a service-account key, a `.env`, or real usage-log lines** in a PR, an issue, or a screenshot.
- **Any change to a `STARLING_` variable must update `.env.example` and the README's Configuration Reference table together**, and any pricing claim must be checked against Google's live pricing page with the check date recorded.

## Reporting Bugs

Open a GitHub issue with:
- Steps to reproduce
- What you expected vs. what happened
- Your Starling version (`starling --version`), OS and Python version
- The relevant lines from `<STARLING_HOME>/logs/errors.log`, **with paths redacted**

## Reporting Security Issues

Do not open a public issue for security vulnerabilities — see [SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
