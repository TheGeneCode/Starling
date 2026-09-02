# Starling Glossary

Shared vocabulary for this project. When in doubt, use these terms exactly as defined
here.

---

## Quick Reference

| Term | One-line definition |
|---|---|
| **Article** | One `.txt` file in the input directory; the unit Starling reads, bills, and archives |
| **Input directory** | Where `read` looks for `.txt` files (`STARLING_INPUT_DIR`, default `~/Starling/input`) |
| **Output directory** | Where the generated `.wav` files are written |
| **Archive** | Where an input file is moved *after* it is successfully synthesized and logged; a failed article stays in the input directory and is retried |
| **Capture pair** | The two clipboard copies `starling capture` collects for one article — the longer becomes the body, the shorter becomes the filename |
| **Voice name** | A full Google voice identifier, e.g. `en-US-Chirp3-HD-Aoede` |
| **Voice family** | The model generation a voice belongs to, derived from its name (`Chirp3-HD`, `Neural2`, `Standard`, `Studio`, `WaveNet`). **Determines the price.** |
| **Voice mode** | `random` (a different voice per article, drawn from the pool) or `fixed` (always `STARLING_VOICE_NAME`) |
| **Voice pool** | The set of voice names `random` mode draws from; defaults to the 22 `en-US-Chirp3-HD-*` voices |
| **Chunk** | One request-sized piece of an article, at most 4,500 UTF-8 bytes, split at a sentence boundary. Chunks are an implementation detail — they are recombined into one `.wav` |
| **Character** | **Google's billing unit.** Every character of the text sent, including spaces and newlines, counted *after* Starling's citation removal |
| **Free tier** | The characters Google does not charge for each month, **per voice family** — 1,000,000 for Chirp 3: HD, 4,000,000 for Standard |
| **Usage log** | The append-only record at `<STARLING_HOME>/logs/usage.log`: one line per article with its character count and the running monthly total |
| **Monthly total** | Characters logged so far in the current calendar month; printed before every file and by `starling usage` |
| **Dry run** | `starling read --dry-run` — reports what would be synthesized and billed, making no API call and needing no credentials |
| **Language code** | A BCP-47 tag such as `en-US` or `en-GB`; scopes which voices exist |
| **Service-account key** | The Google Cloud JSON credential Starling authenticates with. A secret — see [SECURITY.md](SECURITY.md) |
| **`STARLING_HOME`** | The root the input, output, archive and log directories default under (`~/Starling`) |
| **ListVoices** | The unbilled Google API call behind `starling voices`, also used to validate configured voice names before any synthesis is charged |
| **LINEAR16** | The uncompressed audio encoding Starling requests — mono, 16-bit, 24,000 Hz — which is why output is `.wav` and not `.mp3` |

---

## Voice family

Google groups its voices into families that differ in both quality and price. Starling
derives the family from the voice name itself (`en-US-Chirp3-HD-Aoede` → `Chirp3-HD`;
`en-US-Neural2-C` → `Neural2`), because the `ListVoices` API does not return it as a
field — see `starling.voices.model_family`.

**This is the single biggest lever on your bill.** The default family, Chirp 3: HD,
costs US$30 per million characters after its free tier; Standard costs US$4 per million
with a free tier four times larger. Two articles synthesized with different voice
families in the same pool are billed at their own family's rate, not a blended one. See
[What It Costs](README.md#what-it-costs) for the full price table.

## Character

Google's billing unit. Every character sent to `synthesize_speech` is counted, including
spaces and newline characters — there is no discount for whitespace or punctuation.

Starling bills the text **after** cleanup: `remove_citations` (`src/starling/reader.py`)
strips parenthetical academic citations and footnote markers before the character count
is measured, logged, and billed, so citation stripping genuinely reduces what you pay.
The count `--dry-run` reports is this same post-cleanup count, not the raw file size — see
[What It Costs](README.md#what-it-costs).

## Free tier

The number of characters Google does not charge for each calendar month, reset monthly,
and allocated **per voice family** — not per project and not shared across families.
Chirp 3: HD, Neural2, Studio, and Polyglot each get 1,000,000 free characters a month;
Standard and WaveNet each get 4,000,000. Mixing voice families in one pool does not
combine their allowances into a larger pool.

Starling's printed usage percentage is measured against 1,000,000 characters, which is
accurate for the default Chirp 3: HD configuration but overstates usage against the
larger Standard/WaveNet allowance. See [What It Costs](README.md#what-it-costs) and
[Keeping Track](README.md#keeping-track).
