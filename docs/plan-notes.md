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
