# The header screenshot

`docs/screenshot.png` is the terminal-styled image at the top of the README, and — if
set in repository settings (**Settings → General → Social preview**) — GitHub's
social-preview card for the project.

It is **generated**, not hand-taken: `scripts/make_demo_fixture.py` seeds a throwaway
Starling home with public-domain-derived article text and a plausible prior usage log,
`starling read --dry-run` is run against it to capture real stdout (no credentials, no
network, no charges), and `scripts/make_demo_png.py` renders that captured text into a
PNG. Anyone can reproduce the exact same image on any machine, because nothing in it is
invented — the same rule as the rest of this project's pricing and cost claims.

## Regenerating it

**The fixture root must be a neutral directory, not the system temp directory.**
`$env:TEMP` on Windows resolves under `C:\Users\<you>\AppData\Local\Temp`, so its own
path leaks a username into the dry-run report's output-path column. Use a plain
directory such as `C:\starling-demo` instead. Also override every `STARLING_*`
directory and log variable explicitly, not just `STARLING_HOME` — a developer's own
`.env` may set `STARLING_OUTPUT_DIR` (or another directory) independently, and that
takes precedence over `STARLING_HOME` alone.

### PowerShell

```powershell
# 1. Seed a throwaway home at a neutral path.
uv run python scripts/make_demo_fixture.py --root C:\starling-demo

# 2. Capture real output. --dry-run needs no credentials and makes no API call.
#    Every STARLING_* directory is overridden explicitly so a personal .env cannot
#    leak its own paths into the capture, and PYTHONUTF8 avoids the console codepage
#    mangling the report's em dashes.
$env:STARLING_HOME        = "C:\starling-demo"
$env:STARLING_INPUT_DIR   = "C:\starling-demo\input"
$env:STARLING_OUTPUT_DIR  = "C:\starling-demo\output"
$env:STARLING_ARCHIVE_DIR = "C:\starling-demo\archive"
$env:STARLING_USAGE_LOG   = "C:\starling-demo\logs\usage.log"
$env:STARLING_ERROR_LOG   = "C:\starling-demo\logs\errors.log"
$env:PYTHONUTF8           = "1"

"`$ starling read --dry-run" | Out-File -Encoding utf8 "$env:TEMP\session.txt"
uv run starling read --dry-run | Out-File -Encoding utf8 -Append "$env:TEMP\session.txt"

Remove-Item Env:\STARLING_HOME, Env:\STARLING_INPUT_DIR, Env:\STARLING_OUTPUT_DIR, `
  Env:\STARLING_ARCHIVE_DIR, Env:\STARLING_USAGE_LOG, Env:\STARLING_ERROR_LOG, Env:\PYTHONUTF8

# 3. Render.
uv run python scripts/make_demo_png.py --input "$env:TEMP\session.txt" --output docs/screenshot.png
```

### POSIX (macOS/Linux)

`/tmp` does not embed a username, so it is fine as the fixture root here.

```sh
# 1. Seed a throwaway home.
uv run python scripts/make_demo_fixture.py --root /tmp/starling-demo

# 2. Capture real output.
{ echo '$ starling read --dry-run'; \
  STARLING_HOME=/tmp/starling-demo \
  STARLING_INPUT_DIR=/tmp/starling-demo/input \
  STARLING_OUTPUT_DIR=/tmp/starling-demo/output \
  STARLING_ARCHIVE_DIR=/tmp/starling-demo/archive \
  STARLING_USAGE_LOG=/tmp/starling-demo/logs/usage.log \
  STARLING_ERROR_LOG=/tmp/starling-demo/logs/errors.log \
  PYTHONUTF8=1 \
  uv run starling read --dry-run; } > /tmp/session.txt

# 3. Render.
uv run python scripts/make_demo_png.py --input /tmp/session.txt --output docs/screenshot.png
```

## The rule

The image must contain **no real path, username, or article title** — inspect it after
every regeneration, not just the command output. It is generated from **real captured
output**, never from invented text; if the dry-run report's wording or layout changes,
this is the only correct way to update the screenshot.

## When to regenerate

Whenever `print_dry_run`'s output format changes — a new field, a reworded line, a
different flag — or the header art direction changes (colours, layout) in
`scripts/make_demo_png.py`.

## Accepted override

A hand-taken terminal screenshot is fine in place of the generated image, provided it:

- is cropped to the terminal window (no desktop chrome),
- uses a dark theme,
- is at most ~1600 px wide, and
- satisfies the same rule above: no real path, username, or article title.
