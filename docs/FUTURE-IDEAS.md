# Future ideas — parking lot

**This file is for capability the app does not have yet.** Things the app has and gets *wrong*
belong in `docs/BACKLOG.md`.

## Item numbering

**Next item number: 5.**

Item numbers are permanent IDs. Do not renumber when an item ships or is dropped.

1. **Per voice family tracking and displaying** Record which voice families are used and display percentage of each, since each family have their own free caps.
Re-check pricing and caps from Google on a regular cadence and adjust accordingly
Allow features for the user to easily adjust usage of families as needed, e.g. priority and fallback, self imposed caps

2. **Usage percentage aware of multiple voice pools.** The `%` shown today assumes one free
   tier; make it smart enough to handle a different pool per voice family (subsumed by item 1
   if that lands first). *(Moved 2026-09-18 from `dev/TTS/plans/TODO.txt`.)*

3. **README section on never being charged.** Highlight how to set a hard cap: a virtual
   credit card with a $0 limit, a Google Cloud budget alert at $0.01, and whatever else checks
   out. Pricing statements must follow the CLAUDE.md rule (check the pricing page, record the
   date). *(Moved 2026-09-18 from `dev/TTS/plans/TODO.txt`.)*

4. **Output file naming and a launcher shortcut.** Two small usability asks recorded without
   detail: "change local file name?" and "make shortcut?". Decide what each means before
   planning. *(Moved 2026-09-18 from `dev/TTS/plans/TODO.txt`.)*
