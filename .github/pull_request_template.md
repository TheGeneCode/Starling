## What and why

<!-- One or two sentences. Link the issue: "Fixes #123". -->

## Checklist

- [ ] `uv run pytest -q` passes
- [ ] `uv run ruff check` and `uv run ruff format --check` are clean
- [ ] Tests added or updated for behaviour changes
- [ ] `CHANGELOG.md` has an entry under `## [Unreleased]` for a user-visible change
- [ ] A changed `STARLING_` variable is updated in both `.env.example` and the README's Configuration Reference table
- [ ] No service-account key, `.env`, real usage-log lines, or home-directory paths in the diff, screenshots, or this description
