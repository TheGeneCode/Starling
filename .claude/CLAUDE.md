# Starling — Coding Standards

This file is the single source of truth for how code in this repository is written.
`AGENTS.md`, `.trae/rules/instructions.md` and `.github/instructions/instructions.md` are
pointers to it and must not be allowed to accumulate rules of their own.

## Python Coding Standards

- Python ≥ 3.12; use the modern syntax that permits (`X | None`, `StrEnum`,
  `datetime.UTC`).
- Follow Ruff and PEP 8.
- Double quotes for strings.
- Type hints on every function, including tests where they aid clarity.
- `from __future__ import annotations` at the top of every module.
- Module-level constants are annotated `Final`.
- Prefer `@dataclass(frozen=True, slots=True)` for value objects — `StarlingConfig`,
  `ReadOptions`, `DryRunEntry`, `VoiceInfo` are all written this way; match them.
- Prefer list comprehensions over accumulator loops where it stays readable.
- No unused imports (Ruff `F401`).
- Use `pathlib.Path`, never `os.path`.

## Linting & Formatting

- `[tool.ruff.lint]` in `pyproject.toml` is `select = ["ALL"]` with an explicit, commented
  ignore list. **Adding a rule to that ignore list requires a comment saying why**, matching
  the existing entries.
- The Ruff extension auto-fixes on save (import order, trailing commas, whitespace).
- **Do not hand-fix auto-fixable findings.** Focus review effort on type and null
  correctness, logic errors, security, and architecture.
- Suppress a rule inline with a `# noqa: RULE` carrying a reason, only when the rule is
  genuinely wrong for that line — `capture.py`'s `# noqa: S603` on the `subprocess.Popen`
  call is the model.
- `uv run ruff check` must report zero findings before anything is committed.

## Structural Guidelines

- **Prefer modularity.** No file past roughly 1000 lines; propose a logical split into a
  sub-package before it gets there.
- **No code duplication.** If logic is needed twice it becomes a function, parameterized for
  the variation. (This rule was lost from `.trae/rules/instructions.md`; it is restored
  here deliberately.)
- **Separation of concerns.** `config` loads and validates; `voices` resolves and selects;
  `reader` synthesizes; `capture` collects; `cli` only parses arguments and dispatches.
  Keep new code inside whichever of those a reader would expect.
- **File creation.** When implementing a feature, propose the directory structure and
  separate files for logic, types, and tests before writing.
- **Lazy imports in `cli.py`.** The subcommand handlers import their modules inside the
  function body, with `# noqa: PLC0415`. This is load-bearing, not an accident: it keeps
  `starling read` from importing tkinter, and keeps `--help` and `--version` from importing
  anything at all. Preserve it.
- **Injectable seams.** Functions that touch the outside world take the outside world as a
  parameter with a real default — `confirm_overwrite(prompt=input)`,
  `select_voice(rng=None)`, `run_voices(client=None)`,
  `CaptureWindow(clipboard_read=pyperclip.paste, on_close=…)`,
  `load_config(use_dotenv=True)`. New code that calls a network, a clock, a random source,
  or stdin adds the same kind of seam, so it can be tested without one.

## Testing

- `uv run pytest -q`. Never bare `pytest`.
- Tests never make a network call, never construct a real
  `texttospeech.TextToSpeechClient`, and never read real credentials. Pass a mock client;
  use `load_config(use_dotenv=False)` so a developer's `.env` cannot leak into a run.
- Every behaviour change gets a test. Shared fixtures live in `tests/conftest.py`.
- Prefer testing the pure helper directly over driving the Tk mainloop or the argparse
  entry point — `poll_clipboard_once` and `apply_default_command` exist to be called
  directly.

## Documentation Invariants

- The README heading `## Set Up Google Cloud Credentials` is referenced by
  `README_CREDENTIALS_SECTION` in `src/starling/config.py` and asserted in
  `tests/test_config.py`. Do not reword it without changing both.
- `.env.example` and the README's Configuration Reference table describe the same set of
  variables. A change to one is incomplete without the other.
- Any statement about Google Cloud pricing is checked against
  <https://cloud.google.com/text-to-speech/pricing> before it is written, and the check date
  is recorded next to it. Never write a price or a free-tier figure from memory.
- User-visible changes get a `CHANGELOG.md` entry under `## [Unreleased]`.

## Security

- Never commit `.env` or a service-account JSON key. Both are in `.gitignore`; that covers
  this repository only.
- Never print a credential path, a home directory, or real user data into a log, a test
  fixture, a screenshot, or a documentation example.

## Workflow

- After any code change, delegate verification to the QA agent:
  *"Use the @qa-boundary-tester to review these changes for edge cases, write new tests
  where appropriate, and run pytest and Ruff before asking me to commit."*
  Trivial edits — documentation, renames, mechanical refactors — skip the agent and just
  run the build and tests.
- Then, always: `uv run pytest -q` and `uv run ruff check` (zero findings).
- Releases follow [`docs/RELEASING.md`](../docs/RELEASING.md); do not invent a release
  procedure.
