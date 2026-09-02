# Notes for future plans

## Carried forward from Phase 6d (community files, glossary, demo header)

- **Any future maintenance script that runs `starling` and captures its output must
  override *every* `STARLING_*` directory/log variable explicitly, not just
  `STARLING_HOME`.** This repo's own `.env` sets `STARLING_OUTPUT_DIR` directly, which
  takes precedence over `STARLING_HOME` alone (`config.py:load_config` — each directory
  has its own env var, `STARLING_HOME` is only its fallback). `scripts/make_demo_png.py`
  and `docs/DEMO.md`'s regeneration commands learned this the hard way: setting only
  `STARLING_HOME` leaked a real personal path into a captured dry-run report.
- **`$env:TEMP` must not be used as a fixture root for anything whose captured output
  might ship in a doc or image.** It resolves under `C:\Users\<username>\...`, so its
  own path leaks the real username. Use a plain neutral directory (e.g.
  `C:\starling-demo`) on Windows instead; POSIX `/tmp` has no such issue.
- **Capturing CLI stdout to a file on Windows needs `PYTHONUTF8=1`** (or equivalent).
  Without it, Python encodes stdout per the console's active codepage (cp1252 observed
  here), silently corrupting non-ASCII characters (`reader.py`'s em dashes) into bytes
  that are not valid UTF-8 at all — the captured file then fails to even decode. Any
  future script that captures `starling` output for a doc/demo must set this.
- **`scripts/make_demo_fixture.py`'s 5,900-character `civic-primer` article is a single
  run-on sentence with no internal punctuation, on purpose** — this exploits the same
  pre-existing `split_text_into_chunks` quirk noted under "Carried forward from Phase 1"
  (a lone sentence longer than the 4,500-byte cap is never sub-split). If that quirk is
  ever fixed, this fixture's designed 1/1/3 chunk-count invariant breaks and
  `docs/screenshot.png` must be regenerated — `tests/test_make_demo_fixture.py` pins
  this invariant against the real `split_text_into_chunks`, so it will fail loudly
  rather than silently.
- **`scripts/make_demo_png.py`'s `render_session(scale=...)` is unvalidated** —
  `scale <= 0` reaches Pillow's font loader and raises its own `ValueError` rather than
  a guarded message. Harmless today (no CLI flag exposes `scale`; it's a hardcoded
  keyword default), but worth a guard if a future phase ever exposes it as a `--scale`
  flag. Documented and pinned by `test_render_session_non_positive_scale_raises_valueerror`.
- **`_load_fonts`'s fallback is per-family, not per-face**: if a candidate family's
  *regular* face fails to load, its *bold* sibling is never attempted — the whole
  family is skipped and the next candidate family is tried. This is intentional
  (confirmed and pinned by `test_load_fonts_falls_back_to_second_candidate_family`),
  not an oversight; don't "fix" it into trying the bold face alone without a regular
  match.

## Carried forward from Phase 5 (CI, release, icon)

- **`uv tool install starling` / `uvx starling` do not work and never will as written.**
  `[tool.uv.sources]` is development-only config that uv ignores for transitive and
  direct-URL requirements, so genekit is now a PEP 508 direct reference inside
  `project.dependencies` (with `[tool.hatch.metadata] allow-direct-references = true`).
  The two supported install commands are in `docs/RELEASING.md`. **Phase 6's README
  rewrite must not repeat the ROADMAP's `uv tool install starling` claim.**
- **PyPI is closed to this distribution** for as long as the direct reference exists —
  PyPI rejects direct URLs in `Requires-Dist`. Reopening it means publishing genekit's
  `python/` subdirectory to PyPI first. Rationale and the exact reversal are recorded at
  the bottom of `docs/RELEASING.md`.
- **The release workflow hard-fails if the tag, `pyproject.toml`'s version, and
  `CHANGELOG.md` disagree.** The bump-commit-then-tag order in `docs/RELEASING.md` is not
  advisory. Any future automation that creates tags must follow it.
- **CI does not run `ruff format --check`** because the tree still has the pre-existing
  drift in `src/starling/voices.py`, `tests/conftest.py`, `tests/test_config.py`, and
  `tests/test_voices.py` noted under Phase 3c. A whole-tree reformat commit is the
  prerequisite for adding that gate.
- **The wheel-contents assertion in `.github/workflows/ci.yml` is load-bearing**, not
  decoration. It is the only check that catches the icon dropping out of the package or
  the genekit URL reverting to a bare name; both failures are otherwise invisible until
  a user installs.
- **Two Tk import guards exist and are not redundant.**
  `pytest.importorskip("tkinter")` handles a runner with no `_tkinter` (an ImportError
  at module scope would be a collection error, not a skip); the `tk_root` fixture's
  `except tk.TclError` handles Tk present with no display. The Linux CI job needs both.
  If the capture window ever becomes a supported cross-platform surface, the escalation
  is `xvfb-run -a uv run pytest` on the ubuntu job, not removing the guards.
- **Both icon files are provisional placeholders**, generated by
  `scripts/make_placeholder_png.py`. Replacing them requires no code change — the
  procedure is in `resources/icons/README.md`. The generated `.ico` lives at
  `src/starling/resources/starling.ico`, **inside** the package, because hatchling's
  editable install redirects `starling` to `src/starling` and a repo-root `resources/`
  reached only through `force-include` would exist in the wheel but not in a `uv sync`
  development environment.
- **Phase 7 owns the two branding assets that are repo settings, not code**: the GitHub
  social preview image (Settings > General > Social preview) and the README header
  image. Neither is referenced by any source file.

## Carried forward from Phase 4 (update-check)

- **`cli.main()` now calls `maybe_notify_update()` unconditionally, right after
  `parse_args` and before dispatch.** This is the established slot for any future
  startup-time, cross-cutting, must-never-block concern — lazy-imported like the
  subcommand handlers, placed after `parse_args` so `--help`/`--version` (which exit
  inside `parse_args`) stay pure.
- **Plan gap, now a standing rule: a feature wired unconditionally into `cli.main()`
  needs its pre-existing dispatch tests updated in the same phase, not left for QA to
  catch.** Phase 4's own plan wired the update check into every CLI invocation but never
  touched the `test_main_*` dispatch tests written in Phase 3c, which would otherwise
  have silently written to the real `%LOCALAPPDATA%` and hit GitHub's API on every
  unrelated test run. Fixed with a local (not global-conftest) autouse fixture in
  `test_cli.py`. Any future phase that hooks something else into `main()`
  unconditionally should mock it in `test_cli.py` from the start.
- **`requests` is now a direct declared dependency** (`pyproject.toml`), previously only
  transitive via `google-cloud-texttospeech`. `uv lock` added zero new wheels. It stays
  **lazily imported** inside `update_check.get_latest_release()` only — the CLI startup
  path (`cli.py` module scope) must never pay `requests`' import cost. Any future feature
  needing an HTTP client should follow the same lazy-import placement.
- **The GitHub releases API returns nothing until the first `v*.*.*` tag exists.** Until
  Phase 5 ships a real release, `get_latest_release()` legitimately returns `None` every
  time and the update-check notice never prints — this is correct, not a regression to
  chase. Phase 7's exit criterion ("verify the update check sees v0.1.0 from an older
  installed version") is the first point this becomes end-to-end testable, and needs a
  deliberately downgraded `APP_VERSION` to exercise.
- **Two new `candidate`-status genekit ledger sightings exist**
  (`genekit/ledger/CANDIDATES.md`): `user-state-dir` (1 sighting) and
  `release-update-check` (2 sightings, MeadowLark + Starling). Neither is ripe. A future
  phase touching platform-state-directory logic or another release-check should add its
  own sighting rather than re-deriving the pattern from scratch.
- **`state_dir()` hand-rolls the Windows/macOS/XDG branch rather than depending on
  `platformdirs`**, deliberately — `platformdirs` would be a genuinely new wheel for
  ~12 lines. Revisit only if a second, independent need for a full platform-dirs API
  shows up (see the `user-state-dir` ledger entry above).

## Carried forward from Phase 3c

- **The `starling` console-script entry point is live** (`[project.scripts]` in
  `pyproject.toml`, `starling.cli:main`), and `python -m starling` also works via
  `src/starling/__main__.py`. Phase 4 (update check) and Phase 5 (CI/release) can rely on
  both invocation forms existing; no more `python -m starling.reader`/`.voices` anywhere.
- **Lazy-import-inside-handler is the established pattern for subcommand-specific heavy
  deps.** `cli.py`'s `_handle_capture`/`_handle_voices` import `starling.capture`/
  `starling.voices` only inside the handler function, not at module top, so `starling read`
  never loads tkinter and `starling usage` never loads the texttospeech client chain. A
  test (`test_read_does_not_import_tkinter`, subprocess-based) pins this. Any new
  subcommand with its own heavy/optional dependency (e.g. a Phase 4 update-check HTTP
  client) should follow the same pattern rather than importing at module scope.
- **`apply_default_command` and `SUBCOMMANDS`/`TOP_LEVEL_FLAGS` in `cli.py` need updating
  together if a subcommand or top-level flag is ever added** — they are the two lists that
  decide whether a bare-flag invocation like `starling --foo` is treated as `starling read
  --foo` or passed straight to the root parser. Forgetting to add a new top-level flag to
  `TOP_LEVEL_FLAGS` would silently rewrite it into a `read` argument instead.
- **`ruff format --check` on the whole tree still reports pre-existing drift** in
  `src/starling/voices.py`, `tests/conftest.py`, `tests/test_config.py`, and
  `tests/test_voices.py` — flagged already in Phase 3b's notes and left alone again in 3c
  since neither phase's diff touched those specific lines. Whoever next edits those files
  should expect `ruff format` to reflow unrelated lines nearby; a dedicated
  whole-tree-reformat commit (with no logic changes) would clear this cleanly if it starts
  becoming a recurring distraction.
- **README's `## Usage` section was rewritten in 3c to reflect the new CLI**, but the rest
  of the README (Setup Instructions' `pip install -r requirements.txt`, the File Structure
  section listing `articleReader.py`/`requirements.txt`, Troubleshooting) is still stale —
  deliberately out of scope per the 3c plan text ("the full README rewrite is Phase 6").
  Phase 6 should not assume the Usage section is also still wrong; only rewrite it if the
  CLI surface has changed again by then.


Carried forward from Phase 0 (`plans/starling-launch/00-history-and-rename.md`), completed
2026-09-01.

- **Commit email is pinned locally to the GitHub noreply address**
  (`1274287+TheGeneCode@users.noreply.github.com`, set via repo-local `git config user.email`,
  not global). Reason: the account has "block command-line pushes that expose my email"
  enabled, and the first force-push in Phase 0 was rejected (`GH007`) because commits carried
  the real address. Every commit in history was rewritten a second time (`git filter-repo
  --mailmap`) to fix already-pushed history. Do not commit with a different local/global email
  in this repo without expecting the same rejection on push.

- **Final Phase 0 HEAD is `893e6c4` (24 commits), not the SHA implied by the plan's own Step 3
  sanity checks** (`ccad2f2`/`ab7296a`) — those were correct at the time but predate the mailmap
  rewrite above. If a later phase needs to cite a specific pre-Phase-1 SHA, use `893e6c4`.

- **`articleReader.py --follow` count is 16, not the plan's stated 15** — the plan's number was
  computed before Step 2b's extra commit (the W605 raw-string fix) was added. The invariant
  itself (ancestry reaches the root commit, rename from `TTS.py` intact) held; only the plan's
  literal count was stale. If Phase 7 re-runs the V7 assertion from Phase 0, expect 16.

- **Repo is renamed and live at `TheGeneCode/Starling`, still private.** `origin` was removed
  twice by `git filter-repo` (once in Step 3, once in the mailmap rewrite) and re-added both
  times — this is normal filter-repo behavior, not an error, if a future phase runs filter-repo
  again.

## Carried forward from Phase 1

- `.python-version` and `requires-python` were already consistent at 3.12; the 3.11 claim
  was stale commit-message text in `cda68e5`, not a real inconsistency.
- Ruff >= 0.16 enables `CPY001` outside preview, so `select = ["ALL"]` flags every file for
  a missing copyright header. Starling ignores it globally. MeadowLark will hit the same
  wall when its ruff floor moves.
- The genekit dependency ships as `[tool.uv.sources]`, which is uv-only config and does
  **not** survive into wheel metadata. See "Known gaps carried forward" in
  `plans/starling-launch/01-package-skeleton.md` — Phase 5 must resolve it before any PyPI
  publish.
- **This dev machine's hardcoded paths in `reader.py` point to a different Windows user**
  (`C:\Users\user\...` vs. this machine's `C:\Users\etreq\...`), pre-existing and unchanged
  by Phase 1. `output_folder_path.mkdir()` raises `PermissionError` before the input-folder
  glob ever runs, so the plan's "empty `input/` → prints `No text files found.`" manual smoke
  test cannot actually be exercised end-to-end on this machine today. Phase 2 (path
  de-hardcoding) resolves this; until then, don't treat a `reader.py` run's early crash as a
  new regression.
- **QA (`qa-boundary-tester`, Phase 1) characterized 4 pre-existing behavioral quirks with
  passing tests, deliberately not fixed** (Phase 1 forbade touching anything beyond the 6
  measured lint fixes): `split_text_into_chunks` doesn't sub-split a single sentence larger
  than `max_bytes`, and returns `[""]` (not `[]`) for empty input; `convert_numbers_to_words`'s
  currency scaler never labels output "trillion" (only "million"/"billion"); `refine_text`'s
  discard-line matching requires an exact full-line match, so boilerplate variants like
  `"For more info"` don't trigger the `"For more"` cutoff. Whichever phase next touches these
  functions (Phase 2 or 3) should decide whether to fix or intentionally keep.

## Carried forward from Phase 2a

- **`reader.py` now runs on this machine.** `src/starling/config.py` replaced every
  hardcoded path; the manual smoke test (`uv run python -m starling.reader` on an empty
  `~/Starling/input`) now prints "No text files found." and exits 0, confirmed live. The
  `PermissionError`-on-`mkdir` regression noted under "Carried forward from Phase 1" above
  is resolved — a later phase should not treat a `reader.py` crash as pre-existing anymore.
- **`load_config()` never raises for missing credentials; `require_credentials()` does.**
  This split is deliberate so `capture.py` can import config at module scope without
  refusing to open its clipboard-capture window on a machine with no Google key configured
  yet. `02b-voices.md` should keep this split — voice listing/validation needs credentials,
  config loading does not.
- **`require_credentials()` exports `GOOGLE_APPLICATION_CREDENTIALS` into `os.environ`** as
  a side effect, once, on success — this is load-bearing: `google.auth`'s ADC chain only
  reads that exact variable name, so a config that only sets `STARLING_GOOGLE_CREDENTIALS`
  would otherwise fail at `TextToSpeechClient()` construction despite validating cleanly.
  Any future code path that constructs a TTS client must call `require_credentials()` first
  (not just read `config.credentials_path`).
- **`STARLING_VOICE_POOL` blank vs. malformed are different outcomes on purpose.** Empty or
  whitespace-only falls back to `DEFAULT_VOICE_POOL` silently; a value that parses to zero
  names (e.g. `",,,"`) raises `ConfigError`. `02b-voices.md`'s validation step should not
  collapse this distinction — silently substituting a pool the user didn't choose is a
  billing surprise, per the plan's Decisions table.
- **Old `TTS_*` env var names are fully retired, no compatibility shim.** `TTS_MODEL` is
  gone entirely (it was read but never used pre-Phase-2a). Nothing in the codebase reads
  the old names anymore.
- **QA (`qa-boundary-tester`, Phase 2a) added 15 tests** (89 → 104) covering
  `resolve_credentials_path()` precedence/whitespace/tilde in isolation, `parse_voice_pool()`
  as a pure function, `initialize_usage_logger`/`get_monthly_total`'s new optional
  `usage_log_path` override parameter, and `capture.py::run_article_reader()`'s
  platform-gated `creationflags` and exact subprocess argv (previously zero coverage). No
  defects found — all gaps were coverage-only.

## Carried forward from Phase 2b

- **All 22 names in `config.DEFAULT_VOICE_POOL` are still present in Google's live `en-US`
  catalog** — run live on 2026-09-01 via `uv run python -m starling.voices en-US`. Nothing is
  stale; no edit to the tuple is needed.
- **Live catalog has 99 total voices for `en-US` (vs. 22 in default pool)**, across families:
  Casual, Chirp-HD, Chirp3-HD, Neural2, News, Polyglot, Standard, Studio, Wavenet, plus one
  family that `model_family()` cannot classify.
- **Bare single-word voice names appear in the catalog** (~30 entries like `Achernar`, `Puck`,
  `Zephyr`, `Charon`) that look like preview/alias entries for the same underlying Chirp3
  voices also available under their full `en-US-Chirp3-HD-*` names. Both forms are returned by
  `ListVoices`. Because `model_family()` parses family from the dash-separated name structure,
  these bare names fall into `len(parts) < 3`, classified as `"Unknown"` family in
  `format_voices_table`/`pricing_notice` output. A user who copies one into `STARLING_VOICE_POOL`
  passes validation (they're real catalog entries) but gets uninformative billing info. Phase 6
  (pricing verification) should decide whether to special-case these bare names or leave them as
  `"Unknown"` on purpose. Out of scope for Phase 2b.
- **Pre-flight validation ordering is wired correctly** — `fetch_voices` → `validate_voice_names`
  → raise before any `synthesize_speech` call, per the plan, in `reader.py`'s `__main__` block.
  `UnknownVoiceError` subclasses `ConfigError` so the caller's existing `except ConfigError`
  catch handles it with no new except clause needed (new except clause was still added per the
  plan's exact code, listing `UnknownVoiceError` before `ConfigError` for readability).
