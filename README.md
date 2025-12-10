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

The `.env` file has been created for you with default settings:

```
GOOGLE_APPLICATION_CREDENTIALS=C:\Users\user\dev\TTS\tts-service-account.json
TTS_VOICE_NAME=en-US-Neural2-c
TTS_MODEL=chirp-hd
TTS_LANGUAGE_CODE=en-US
```

#### Optional: Change Voice Settings

Available US English voices with lower/neutral pitch:
- `en-US-Neural2-c` (female, lower pitch) - **[DEFAULT]**
- `en-US-Neural2-e` (female, neutral)
- `en-US-Neural2-f` (female, neutral)
- `en-US-Neural2-i` (male, neutral)
- `en-US-Neural2-j` (male, slightly lower pitch)

To change the voice, edit the `.env` file and set `TTS_VOICE_NAME` to your preferred voice.

## Usage

1. Place your `.txt` files in the `input/` directory
2. Run the script:
   ```powershell
   python articleReader.py
   ```
3. The script will:
   - Remove academic citations from the text
   - Automatically split long articles into 4.5KB chunks (safe for the 5KB API limit)
   - Convert each chunk to speech using Google Cloud TTS (ChirpHD model)
   - Combine all audio chunks into a single seamless `.wav` file
   - Save audio to your output directory
   - Archive processed files to the `archive/` directory
   - Log usage to `tts_usage.log`

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
