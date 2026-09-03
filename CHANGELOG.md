# Changelog

All notable changes to Starling are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- README section **Staying on the Free Tier** — what each Google Cloud protection actually
  buys you, with console steps for a budget alert, a Text-to-Speech quota cap, and disabling
  the API between batches, plus what to do if a charge appears.
- `starling read --confirm`: prints the `--dry-run` cost report, then asks before synthesizing.
- `STARLING_CAPTURE_CONFIRM`: when set, `starling capture` launches the reader with `--confirm`
  instead of synthesizing immediately. Off by default; existing behavior is unchanged.

### Changed

- Number-to-words conversion (`1,234` → `one thousand two hundred and thirty-four`,
  `$1,300 million` → `1.3 billion dollars`) now happens in `read` instead of `capture`,
  so a `.txt` file placed in the input directory by hand gets the same conversion as one
  `capture` saved.

## [0.1.0] - 2026-09-02

First public release. Starling began as a private collection of scripts and became an
installable command-line tool.

### Added

- `starling` command-line interface with `read`, `capture`, `voices`, and `usage`
  subcommands; `read` is the default when no subcommand is given.
- `starling read --dry-run` reports what would be synthesized and how many characters it
  would bill, without calling the Google API. `--yes` skips the overwrite prompt so the
  tool is scriptable.
- `starling voices` queries Google's live voice catalog for a language code, so the list
  never goes stale, and configured voice names are validated before any synthesis is
  billed.
- Configuration through `STARLING_`-prefixed environment variables with cross-platform,
  user-relative defaults. Every variable is documented in `.env.example`.
- Weekly, non-blocking update check against the GitHub releases API, opt-out via
  `STARLING_UPDATE_CHECK=0`. Network failures are silent no-ops.
- Clipboard-capture window (`starling capture`) with a Windows title-bar and taskbar
  icon.
- Continuous integration on Windows and Linux across Python 3.12 and 3.14, and a tagged
  release workflow that publishes the wheel and sdist to GitHub Releases.
- `CONTRIBUTING.md`, `SECURITY.md` (with a runbook for a leaked service-account key),
  `CODE_OF_CONDUCT.md`, `GLOSSARY.md`, and a generated terminal-capture header image
  with the scripts to regenerate it.

### Changed

- Every hardcoded absolute path belonging to the original author was replaced with
  configuration; the tool now runs on a machine that has never seen the author's home
  directory.
- `genekit` is declared as a PEP 508 direct reference so the published wheel is
  installable outside a source checkout.
- README rewritten for a general audience: corrected install instructions (the bare
  PyPI name `starling` is an unrelated project; Starling installs from its git
  repository), verified Google Cloud pricing and free-tier figures against Google's
  pricing page, and removed the author-specific paths.
- Coding standards consolidated into `.claude/CLAUDE.md`; `AGENTS.md`,
  `.trae/rules/instructions.md` and the new `.github/instructions/instructions.md` now
  point at it.

### Removed

- The `kittentts` and `pandas` dependencies, neither of which was used by shipping code.

## [0.0.2] - 2026-09-02

- testing release script

## [0.0.1] - 2026-09-02

- test release

[Unreleased]: https://github.com/TheGeneCode/Starling/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/TheGeneCode/Starling/compare/v0.0.2...v0.1.0
[0.0.2]: https://github.com/TheGeneCode/Starling/compare/v0.0.1...v0.0.2
[0.0.1]: https://github.com/TheGeneCode/Starling/releases/tag/v0.0.1
