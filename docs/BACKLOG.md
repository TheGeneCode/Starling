# Backlog — known defects

Things that are **wrong**, not things that are missing. New capability lives in
`docs/FUTURE-IDEAS.md`; engineering debt/leverage in `docs/ENGINEERING-IMPROVEMENTS.md`.

Ordered by severity, and severity here means *what it costs a read-aloud run or a release*, not
what it costs to fix. Every entry names the mechanism and the file, so the fix does not start
with a re-diagnosis.

## Issue numbering

**Next issue number: 10.**

Issue numbers are permanent IDs. Do not reuse a number when an issue is closed or removed.

Items 1-8 were filed 2026-09-18 by a cross-project tooling audit (tree at "fix: correct
formatting issues in CHANGELOG.md", 2026-09-03, plus uncommitted `.claude/` changes). The
system-wide half of the same audit is in `dev/backlog.txt`.

## Open

### 5. `normalize_version` is byte-identical to MeadowLark's

`src/starling/update_check.py:55` and MeadowLark `src/version_utils.py:51` are the same
function. Recorded in `genekit/ledger/CANDIDATES.md` under `release-update-check` (2 sightings,
one short of ripe). Nothing to do here until a third repo appears, except not to let the two
copies diverge.

### 6. Release tooling forked from MeadowLark and drifting

`scripts/release.ps1` (136 lines vs MeadowLark's 78), `scripts/make_icon.py`,
`scripts/make_social_preview.py` and `.github/workflows/release.yml` (80 vs 55 lines) began as
copies of MeadowLark's and have diverged in both directions. Each release-process fix now lands
in one repo. `dev/backlog.txt` item 14 covers the shared solution. Which copy is newer is
recorded in `docs/RELEASING.md` (Starling's, 2026-09-24), so the next fix starts from it.

### 7. it reads out "quote quote quote quote quote quote" sometimes (can't be fixed by my code, seems to be a google )
https://coloradosun.com/2026/10/03/manny-rutinel-website-changes-8th-congressional-district/
that's an example where it did it a couple times, reading out 4 to 6 quotes. it's confusing it doesn't just read every quote mark

Diagnosis so far (2026-10-06): the archived input has no repeated quote characters, only
paired `“ ”`. Several sentences carry 4 or 6 of them, matching "4 to 6 quotes", e.g. three
short quoted phrases in one sentence. Both synthesis chunks are quote-balanced, so a chunk
boundary does not orphan a quote. Starling sends the text unchanged, which makes this
Chirp 3 HD model output, and it is not deterministic. Normal "quote" reading is wanted;
stripping or announcing every quote was rejected. Next step needs the failing audio: keep the
`.wav` and note roughly where it happens, then test against it (smaller chunks, ASCII quotes).

### 8. Trillion translated to "thousand billion"
https://coloradosun.com/2026/10/03/manny-rutinel-website-changes-8th-congressional-district/ is the article it happened in
I would like Trillion to be a standard word, it doesn't need translating. Quadrillion, Quintillion, Sextillion, Septillion, and Octillion, Nonillion, Dectillion are words I know the meaning of as well. Anything bigger than that can be translated into a smaller version (i.e. a thousand Sextillion = Septillion equivalent)

Fixed 2026-10-06 (uncommitted). `scale_currency` in `src/starling/reader.py` only labelled
output "million" or "billion", so "$3 trillion" became "3000 billion dollars". It now picks
the largest word from million to decillion and keeps amounts past that in decillions. Move to
Closed once committed.

### 9. let the user know about errors
When an article fails to output a .wav, I often don't know. I only notice that the article tries is in the next batch again eventually. Errors like that should be output to the terminal and the terminal held open if there are any errors to display.

## Closed

### 9. `starling capture` imports the whole Google TTS stack before opening its window

Closed 2026-09-24. All three fixes landed. `cli.py` imports `starling.reader` inside
`_handle_read` / `_handle_usage`; `starling.__version__` resolves on first access (module
`__getattr__`) and `--version` uses a lazy action, so `importlib.metadata` is not imported
either; capture passes the update check to `run_capture(on_ready=...)`, which runs it
`ON_READY_DELAY_MS` after the window is up. Measured after (warm cache, `-X importtime`):
`import starling.cli` ~25 ms (was ~0.75 s); `starling.cli` + `starling.capture` load 142
modules (was 661). `test_capture_does_not_import_reader_or_version_metadata` in
`tests/test_cli.py` guards it. The `uv sync --compile-bytecode` note still applies.

### 1. genekit is pinned at `py-v0.1.0`; every other consumer is on `py-v0.3.1`

Closed 2026-09-24. Commit 93e45f3 (atomic_write migration) bumped the pin to `py-v0.4.0`, the
latest `py-v*` tag; `uv lock --check` is clean and the installed version is 0.4.0. The consumers
registry in `genekit/python/README.md` lists this repo as "Starling" at `py-v0.4.0`.

### 2. No `permissions.allow` list, so every `uv run` prompts

Closed 2026-09-24. Commit fe5b160 added `permissions.allow` to `.claude/settings.json` covering
`uv run *` and `uv sync *` for both the Bash and PowerShell tools.

### 3. `ruff format` drift, and CI deliberately does not check it

Closed 2026-09-24. Commit a7f5799 reformatted the whole tree; d3b3e0f added the
`uv run ruff format --check` step to `.github/workflows/ci.yml`. `ruff format --check` reports
all 45 files formatted.

### 4. No `.gitattributes`

Closed 2026-09-24. Commit 2590697 added `.gitattributes` (LF for text, CRLF for `*.ps1`,
binaries marked).

### 7. `line-length` unset in `pyproject.toml`

Closed 2026-09-24. `[tool.ruff]` now sets `line-length = 100` (commits a7f5799, 9a6253f).

### 8. Verify the kittentts removal left nothing behind

Closed 2026-09-24. No `kittentts` in `uv.lock` or `pyproject.toml`; `CHANGELOG.md` records the
removal under `### Removed`.
