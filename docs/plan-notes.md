# Notes for future plans

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
