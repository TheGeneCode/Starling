# Article Reader - Google Cloud TTS

Converts text articles to speech using Google Cloud Text-to-Speech API with usage tracking.

## Setup Instructions

### 1. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 2. Set Up Google Cloud Credentials

#### Create a Google Cloud Project
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the **Project** dropdown at the top
3. Click **NEW PROJECT**
4. Enter a project name (e.g., "TTS-Article-Reader")
5. Click **CREATE**
6. Wait for the project to be created, then select it from the dropdown

#### Enable the Text-to-Speech API
1. In the Cloud Console, go to **APIs & Services** > **Library**
2. Search for "Text-to-Speech"
3. Click on **Cloud Text-to-Speech API**
4. Click **ENABLE**

#### Create a Service Account
1. Go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** > **Service Account**
3. Fill in the details:
   - Service account name: `tts-reader` (or any name)
   - Service account ID: auto-fills
   - Description: `Service account for article TTS conversion`
4. Click **CREATE AND CONTINUE**
5. Click **CONTINUE** (skip the optional steps)
6. Click **DONE**

#### Generate and Download the JSON Key File
1. In **Credentials**, find your new service account and click on it
2. Go to the **KEYS** tab
3. Click **ADD KEY** > **Create new key**
4. Select **JSON**
5. Click **CREATE** - the JSON file will automatically download

#### Place the JSON File
1. Save the downloaded JSON file in your TTS project directory as: `tts-service-account.json`
   - Full path: `C:\Users\user\dev\TTS\tts-service-account.json`

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and set at least your credentials path:

```
STARLING_GOOGLE_CREDENTIALS=~/starling-service-account.json
```

Every other setting is optional and defaults to a subdirectory of `~/Starling` — see
`.env.example` for the full list (`STARLING_HOME`, `STARLING_INPUT_DIR`,
`STARLING_OUTPUT_DIR`, `STARLING_ARCHIVE_DIR`, `STARLING_USAGE_LOG`, `STARLING_ERROR_LOG`,
`STARLING_LANGUAGE_CODE`, `STARLING_VOICE_MODE`, `STARLING_VOICE_NAME`,
`STARLING_VOICE_POOL`) with defaults and comments.

> **Migration note:** the old `TTS_VOICE_NAME` / `TTS_LANGUAGE_CODE` variables were renamed
> to `STARLING_VOICE_NAME` / `STARLING_LANGUAGE_CODE`; `TTS_MODEL` was removed (it was read
> but never used). `GOOGLE_APPLICATION_CREDENTIALS` still works as a fallback if you don't
> set `STARLING_GOOGLE_CREDENTIALS`.

#### Optional: Change Voice Settings

By default Starling picks a different voice at random from a pool of 22
`en-US-Chirp3-HD-*` voices for each file. Set `STARLING_VOICE_MODE=fixed` and
`STARLING_VOICE_NAME=<voice>` to always use one voice instead, or set
`STARLING_VOICE_POOL` to a comma-separated list to restrict the random pool. Voice families
are priced differently on your Google Cloud account — see the pricing note in
`.env.example` before switching families.

## Usage

Install the `starling` command:

```powershell
uv tool install starling
```

Or run it straight from a checkout without installing:

```powershell
uvx --from . starling --help
```

Starling has four subcommands. Bare `starling` (no subcommand) is shorthand for
`starling read`.

| Command | What it does |
|---|---|
| `starling read [--input-dir PATH] [-y\|--yes\|--overwrite] [--dry-run]` | Synthesize every `.txt` in the input directory. The default command. |
| `starling capture` | Open the clipboard-capture window that saves articles into the input directory. |
| `starling voices [LANGUAGE_CODE]` | List the Google voices available for a language (defaults to `STARLING_LANGUAGE_CODE`). |
| `starling usage` | Print this month's character total from the usage log. |

`read` flags:
- `--input-dir PATH` — read `.txt` files from `PATH` for this run instead of `STARLING_INPUT_DIR`.
- `-y`, `--yes`, `--overwrite` — overwrite an existing `.wav` without prompting.
- `--dry-run` — report what would be synthesized and billed, without calling Google or needing credentials.

```powershell
starling read --dry-run
starling read --yes
starling voices en-GB
starling usage
```

Each run:
- Removes academic citations from the text
- Automatically splits long articles into 4.5KB chunks (safe for the 5KB API limit)
- Converts each chunk to speech using Google Cloud TTS
- Combines all audio chunks into a single seamless `.wav` file
- Saves audio to your output directory
- Archives processed files to the archive directory
- Logs usage to the usage log

## Usage Tracking

All TTS usage is logged to `tts_usage.log` with:
- **Timestamp** - When the conversion was done
- **Filename** - The processed article
- **Voice** - The voice used
- **Character Count** - Characters processed
- **Monthly Total** - Running character count that resets monthly

Example log entry:
```
2025-12-10 14:32:15 | article-title | voice: en-US-Neural2-c | characters: 5,234 | monthly total: 125,432
```

## Cost Monitoring

Google Cloud TTS offers free quotas:
- **Standard voices**: 1 million characters/month free
- **Neural2 voices**: 500,000 characters/month free
- **Chirp models**: 1 million characters/month free

Check your `tts_usage.log` monthly total to ensure you stay within free tier limits.

## File Structure

```
.
├── articleReader.py          # Main script
├── .env                      # Environment variables (git-ignored)
├── tts-service-account.json  # Google Cloud credentials (git-ignored)
├── requirements.txt          # Python dependencies
├── .gitignore               # Files to exclude from git
├── logfile.txt              # Error log (git-ignored)
├── tts_usage.log            # Usage tracking log (git-ignored)
├── input/                   # Input text files
├── output/                  # Output audio files
└── archive/                 # Processed files
```

## Troubleshooting

**Error: "GOOGLE_APPLICATION_CREDENTIALS not found"**
- Ensure the `tts-service-account.json` file is in the correct location
- Verify the path in `.env` matches your actual file location

**Error: "Import 'google.cloud.texttospeech' could not be resolved"**
- Run `pip install -r requirements.txt` to install dependencies

**Character limit exceeded**
- Check `tts_usage.log` for your monthly total
- Consider upgrading your Google Cloud billing plan for higher quotas
