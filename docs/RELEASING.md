# Releasing Starling

Releases are cut by pushing a `vX.Y.Z` tag. `.github/workflows/release.yml` does the
rest: it first runs the whole CI workflow (tests, lint, format, package checks) as a gate,
then verifies the tag against the committed version, builds the sdist and wheel,
smoke-tests the wheel in a clean environment, writes `SHA256SUMS`, attests build
provenance, and publishes a GitHub Release whose notes are this version's `CHANGELOG.md`
section plus download-verification instructions.

The workflow **fails** if CI fails on the tagged commit, if the tag and `pyproject.toml`
disagree, or if `CHANGELOG.md` has no section for the version. Follow the steps in order
and none of those happens.

`scripts\release.ps1` automates the checklist below (tests/lint, changelog rewrite,
version bump, commit, tag, push) with a single confirmation prompt. Run it from the repo
root: `.\scripts\release.ps1 -Version X.Y.Z`.

## Checklist

1. **Green on `main`.**

   ```
   uv sync --group dev --locked
   uv run pytest -q
   uv run ruff check
   ```

2. **Update `CHANGELOG.md`.** Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`,
   add a fresh empty `## [Unreleased]` above it, and update the two link definitions at
   the bottom of the file.

3. **Bump the version and re-lock.**

   ```
   uv version X.Y.Z
   uv lock
   ```

   `uv.lock` records the project's own version, so skipping `uv lock` makes CI's
   `uv sync --locked` fail on the very next push.

4. **Commit.**

   ```
   git commit -am "chore(release): vX.Y.Z"
   ```

   The commit email is pinned repo-locally to
   `1274287+TheGeneCode@users.noreply.github.com`. The account blocks command-line
   pushes that expose the real address; committing with a different email produces a
   `GH007` rejection on push.

5. **Tag and push.**

   ```
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin main --follow-tags
   ```

6. **Watch the run.** Confirm the Release workflow succeeds, that
   `starling-X.Y.Z-py3-none-any.whl`, `starling-X.Y.Z.tar.gz` and `SHA256SUMS` are attached
   to the release, and that the notes show the CHANGELOG section. Optionally download the
   wheel and run
   `gh attestation verify starling-X.Y.Z-py3-none-any.whl --repo TheGeneCode/Starling`.

7. **Verify the install actually works**, from a machine or container that is not a
   source checkout:

   ```
   uv tool install "starling @ git+https://github.com/TheGeneCode/Starling@vX.Y.Z"
   starling --version
   ```

## If a release goes wrong

`v*` tags are immutable: a repository ruleset ("Immutable release tags") blocks deleting,
moving, or force-updating them, because users install from the tag itself (`@vX.Y.Z`), not
from the Release assets. A tag that exists is installable even if its Release job failed.

- **Fix forward.** Bump to the next patch version and release again. A failed run leaves a
  tag with no GitHub Release; say so in the next version's CHANGELOG entry (for example
  "0.3.0 was tagged but never released; use 0.3.1").
- **Escape hatch, only if nobody can have installed it** (it failed within minutes):
  Settings → Rules → Rulesets → **Immutable release tags** → Enforcement **Disabled**;
  `git push --delete origin vX.Y.Z`; set Enforcement back to **Active** straight away; fix;
  re-tag.

## Shared ancestry with MeadowLark: start from this copy

The release tooling began as copies of MeadowLark's and has diverged. **Starling's copy is
the more developed one; when fixing a release-process bug, start here and port the fix
across, not the other way.** As of 2026-09-24:

- `scripts/release.ps1` — Starling's adds a `main`-branch and clean-tree guard, runs the
  checks, rewrites `CHANGELOG.md` (heading and link definitions, with duplicate-section
  guards), and runs `uv lock`. MeadowLark's only stamps the version, commits with
  `git add .`, tags, and pushes.
- `.github/workflows/release.yml` — as of 2026-11-08 both share one shape: a callable-CI gate
  (`needs: ci`), SHA-pinned actions, no uv cache in the publishing job,
  `persist-credentials: false`, a SHA256 checksum, a provenance attestation, and notes the job
  writes itself. They still differ in what they build: MeadowLark's builds a PyInstaller exe and
  an Inno Setup installer on Windows; Starling's builds a `py3-none-any` wheel on Linux, with
  notes taken from `CHANGELOG.md`.
- `scripts/make_icon.py` — Starling writes the `.ico` into the package
  (`src/starling/resources/`) so it ships in the wheel; MeadowLark writes it beside the
  source PNG.
- `scripts/make_social_preview.py` — same script with different palette and text. Starling's
  adds the font-fallback chain and a wider comment on the aspect-ratio reasoning.

The shared solution is `dev/backlog.txt` item 14; until it lands, a fix to any of these
files should be checked against the other repo's copy.

## Monthly maintenance check

`.github/workflows/maintenance-check.yml` runs `scripts/check_pins.py` on the 1st of each month
(and on demand: `gh workflow run maintenance-check.yml`). It keeps one issue, "Monthly maintenance
check", listing what is due: a newer genekit `py-v*` tag than the pin, a released CPython above the
`classifiers` ceiling, a `google-cloud-texttospeech` major at or above the cap, a README pricing
check older than 90 days, or a `uv.lock` change since the last tag. A check that cannot run (network,
parse error) is listed too, so silence always means "checked and fine". When nothing is due, it
closes the issue. Dependabot handles everything else (actions SHAs and `uv.lock`).

## Why there is no PyPI publish

`genekit` is declared as a PEP 508 direct reference
(`genekit @ git+https://github.com/TheGeneCode/genekit@...`) because uv's
`[tool.uv.sources]` is development-only configuration and is ignored for direct-URL and
transitive requirements — a plain `Requires-Dist: genekit` would send every installer
looking on PyPI, where genekit does not exist. PyPI rejects uploads whose metadata
contains direct references, so this distribution is structurally ineligible.

Publish genekit's `python/` subdirectory to PyPI first. Then the direct reference can
revert to a plain `genekit>=X.Y`, and a PyPI job can be added to the release workflow
using uv's documented trusted-publishing split (a `build` job with `contents: read` and
a separate `publish` job holding `id-token: write`).
