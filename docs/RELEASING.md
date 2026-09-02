# Releasing Starling

Releases are cut by pushing a `vX.Y.Z` tag. `.github/workflows/release.yml` does the
rest: it verifies the tag against the committed version and the changelog, builds the
sdist and wheel, smoke-tests the wheel in a clean environment, and attaches both to a
GitHub Release.

The workflow **fails** if the tag and `pyproject.toml` disagree, or if `CHANGELOG.md`
has no section for the version. Follow the steps in order and neither happens.

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

6. **Watch the run.** Confirm the Release workflow succeeds and that both
   `starling-X.Y.Z-py3-none-any.whl` and `starling-X.Y.Z.tar.gz` are attached to the
   release.

7. **Verify the install actually works**, from a machine or container that is not a
   source checkout:

   ```
   uv tool install "starling @ git+https://github.com/TheGeneCode/Starling@vX.Y.Z"
   starling --version
   ```

## If a release goes wrong

- **Nobody could have installed it yet** (failed within minutes, no downloads): delete
  the GitHub Release and the tag (`git push --delete origin vX.Y.Z`), fix, and re-tag
  the same version.
- **Otherwise**: never re-point a published tag. Fix forward with a patch release.

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
