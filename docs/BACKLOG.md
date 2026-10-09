# Backlog — known defects

Things that are **wrong**, not things that are missing. New capability lives in
`docs/FUTURE-IDEAS.md`; engineering debt/leverage in `docs/ENGINEERING-IMPROVEMENTS.md`.

Ordered by severity, and severity here means *what it costs a read-aloud run or a release*, not
what it costs to fix. Every entry names the mechanism and the file, so the fix does not start
with a re-diagnosis.

## Issue numbering

**Next issue number: 15.**

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

## Closed

### 14. Captured articles are saved with `\r\r\n` line endings

Found 2026-10-09 while diagnosing #10. On Windows the clipboard text already has `\r\n`.
`CaptureWindow._save_pair` in `src/starling/capture.py` writes it with `Path.write_text`, whose
text mode turns each `\n` into `\r\n`. Every line then ends `\r\r\n`, and editors show twice the
real line count (line 23 shows as line 45). Speech is unaffected: `read` reads with
universal newlines and the sentence split collapses whitespace.

Closed 2026-10-09. `refine_text` now converts `\r\n` and lone `\r` to `\n` before anything else,
so the text-mode write emits one native line ending. Files already saved keep their `\r\r\n`.

### 13. Each synthesis chunk's WAV header is played as audio

Found 2026-10-09 while diagnosing #10. With `LINEAR16`, Google returns each chunk's
`audio_content` with its own 44-byte RIFF header. `synthesize_text` in
`src/starling/reader.py` passed those bytes straight to `combine_audio_chunks`, which joins
them as raw PCM and wraps the result in a new header. So every output had a stray header at
byte 44 and one more at each chunk join, each played as about 22 samples of noise, a short click.
The San Luis Valley ranch `.wav` has them at bytes 44 and 12,172,888 (about 4:13).

Closed 2026-10-09, fixed per `plans/strip-chunk-wav-headers.md`. `synthesize_text` now passes
each chunk through `wav_pcm_frames`, which reads the frames with `wave` and rejects a chunk whose
format differs from the request. Existing .wav files keep their clicks; re-synthesize to remove
them.

### 12. Read failures are not reported, and the reader's console closes on them (filed as #9)

Reported: when an article failed to become a `.wav` the user did not find out, and only noticed
when the article came round again in a later batch.

Closed 2026-10-06, fixed per `plans/report-read-errors-hold-console.md`. `starling capture`
launches `read` in a `CREATE_NEW_CONSOLE` window that closed on exit, taking each mid-run error
message with it, and `run_read` exited 0 regardless. `process_file` now returns a `FileResult`,
and `run_read` ends with a list of every failed file and its reason (archive failures included)
and exits 1. `read --pause-on-error`, which `run_article_reader` always passes, waits for Enter
on any non-zero exit, including config/credential errors and an unexpected crash (printed as a
traceback).

### 11. Trillion read as "thousand billion" (filed as #8)

Closed 2026-10-06 in commit 86494dc. `scale_currency` in `src/starling/reader.py` only labelled
output "million" or "billion", so "$3 trillion" became "3000 billion dollars". It now picks the
largest word from million to decillion and keeps amounts past that in decillions.

### 10. Voice sometimes reads "quote quote quote quote" (filed as #7)

Reported on a Colorado Sun article (2026-10-03): 4 to 6 "quote"s read out in a row a couple of
times, not every quote mark.

First closed 2026-10-06 as model output: that article's two chunks were quote-balanced.
Reopened 2026-10-09 with a failing `.wav` (San Luis Valley ranch article, 2:57: "regarding the
quote ×9" in place of “working relationship”). `split_text_into_chunks` split at a sentence
end inside a quotation, so chunk 0 ended in an unclosed `“`. Re-synthesized with the same voice
and transcribed locally: the as-sent chunk looped 3/3, ASCII quotes 1/3, the same chunk cut
before the quotation 0/3, and the paragraph alone 0/10. 13 of 66 archived multi-chunk articles
had such a split. Fixed the same day: chunk boundaries fall only outside `“…”` passages.
A single "quote," still occurs (6/10 on the paragraph alone). That is normal reading, and
stripping or announcing every quote was rejected. The 10-03 article looped with balanced
chunks, so Chirp 3 HD can still do it rarely without a mid-quote split.

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
