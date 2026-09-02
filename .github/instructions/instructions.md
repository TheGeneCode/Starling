---
applyTo: "**/*.{py,pyi}"
---

# Python Coding Standards

The full standards for this repository are in
[`.claude/CLAUDE.md`](../../.claude/CLAUDE.md). Read it before writing or reviewing Python
here. The essentials:

- Python ≥ 3.12, `from __future__ import annotations`, double quotes, type hints on every
  function, `pathlib` over `os.path`.
- Ruff runs with `select = ["ALL"]`. Do not hand-fix auto-fixable findings; do not add to
  the ignore list in `pyproject.toml` without a comment explaining why.
- No file past ~1000 lines. No duplicated logic — extract a parameterized function.
- Tests never touch the network or real credentials. Run `uv run pytest -q` and
  `uv run ruff check` after any change.
