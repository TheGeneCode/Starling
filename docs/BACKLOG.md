# Backlog — known defects

Things that are **wrong**, not things that are missing. New capability belongs in
`plans/FUTURE-IDEAS.md`.

Ordered by severity, and severity here means *what it costs a read-aloud run or a release*, not
what it costs to fix. Every entry names the mechanism and the file, so the fix does not start
with a re-diagnosis.

## Issue numbering

**Next issue number: 9.**

Issue numbers are permanent IDs. Do not reuse a number when an issue is closed or removed.

Items 1-8 were filed 2026-09-18 by a cross-project tooling audit (tree at "fix: correct
formatting issues in CHANGELOG.md", 2026-09-03, plus uncommitted `.claude/` changes). The
system-wide half of the same audit is in `dev/backlog.txt`.

## Open

### 1. genekit is pinned at `py-v0.1.0`; every other consumer is on `py-v0.3.1`

`pyproject.toml` `dependencies` carries `genekit @ git+...@py-v0.1.0`. py-v0.3.1 fixed
`format_timestamp` cross-platform behaviour and shipped `genekit.tz`; nothing here uses `tz`
yet, but the pin is two minors and one bugfix behind and the consumers registry in
`genekit/python/README.md` still lists this repo under its old name "TTS". Run `/genekit bump`,
re-lock, and fix the registry row.

### 2. No `permissions.allow` list, so every `uv run` prompts

`.claude/settings.json` has no `permissions.allow` list. Add the common allowlist from
MeadowLark. (The hook half of this item is resolved: `post_edit_ruff.py` and its registration
are now the global hook in `~/.claude/hooks/`, not a local copy — see `dev/backlog.txt` item 3.)

### 3. `ruff format` drift, and CI deliberately does not check it

15 of 44 files differ from `uv run ruff format` output. `.github/workflows/ci.yml` has a comment
reserving the `ruff format --check` step "after a dedicated whole-tree reformat commit"
(`docs/plan-notes.md` records the four files first noticed). Do that commit, then enable the
step in CI.

### 4. No `.gitattributes`

The repo relies on each tool's defaults for line endings; `.claude/hooks/post_edit_ruff.py` is
byte-identical to MeadowLark's except for CRLF. Copy a sibling repo's `.gitattributes`.

### 5. `normalize_version` is byte-identical to MeadowLark's

`src/starling/update_check.py:55` and MeadowLark `src/version_utils.py:51` are the same
function. Recorded in `genekit/ledger/CANDIDATES.md` under `release-update-check` (2 sightings,
one short of ripe). Nothing to do here until a third repo appears, except not to let the two
copies diverge.

### 6. Release tooling forked from MeadowLark and drifting

`scripts/release.ps1` (136 lines vs MeadowLark's 78), `scripts/make_icon.py`,
`scripts/make_social_preview.py` and `.github/workflows/release.yml` (80 vs 63 lines) began as
copies of MeadowLark's and have diverged in both directions. Each release-process fix now lands
in one repo. `dev/backlog.txt` item 14 covers the shared solution; locally, note which copy is
the newer one in `docs/RELEASING.md` so the next fix starts from it.

### 7. `line-length` unset in `pyproject.toml`

`[tool.ruff]` sets `src` only; line length falls to ruff's default 88 while MeadowLark's sibling
config and every other repo use 100. Either is fine; the mismatch means shared snippets and
cross-repo copy of code reformat on arrival. Pick 100 to match.

### 8. Verify the kittentts removal left nothing behind

`dev/TTS/plans/TODO.txt` asked: "kittentts is dropped right? drop tests associated with it
too". `rg -i kittentts src tests README.md` finds nothing on 2026-09-18, so this looks done;
check `uv.lock`, `pyproject.toml` and `CHANGELOG.md` for a removal entry, then close.
*(Moved from `dev/TTS/plans/TODO.txt`.)*

## Closed

(none yet)
