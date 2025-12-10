"""Processes all .txt files in the specified input directory by removing citations, converting the text to speech using Google Cloud TTS, and saving the resulting audio as .wav files in the output directory. Displays a spinner animation during processing, handles file overwrites with user confirmation, logs errors and usage, and moves processed files to an archive directory."""

import io
import itertools
import logging
import re
import shutil
import sys
import time
import wave
from datetime import datetime, timezone
from os import getenv
from pathlib import Path
from threading import Event, Thread

from dotenv import load_dotenv
from google.cloud import texttospeech

# from kittentts import KittenTTS

# Load environment variables from .env file
load_dotenv()


def spinner(should_spin: Event) -> None:
    """
    Display a spinning animation on the console while a task is being executed.

    Args: should_spin (Event): An Event object that controls whether the spinner animation should continue spinning or stop.
    """
    chars = itertools.cycle("-\|/")  # noqa: W605
    while should_spin.is_set():
        char = next(chars)
        print(f"Speaking... {char}", end="\r")
        time.sleep(0.1)


def remove_citations(text: str) -> str:
    citations_regex = r"\([^\)]+(?:,\s*\d{4}(?:[a-zA-Z]?)?(?:,\s*p\.\s*\d+)?)+\)"
    return re.sub(citations_regex, "", text)


def initialize_usage_logger() -> logging.Logger:
    """Initialize and return a logger for TTS usage tracking."""
    usage_logger = logging.getLogger("tts_usage")
    usage_logger.setLevel(logging.INFO)

    # Create handler for usage log file
    handler = logging.FileHandler("tts_usage.log")
    handler.setLevel(logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    usage_logger.addHandler(handler)

    return usage_logger


def get_monthly_total() -> dict:
    """
    Parse the usage log and return character count and details for current month.

    Returns:
        dict: Contains 'total_chars', 'current_month', 'entries' (list of log entries)
    """
    current_date = datetime.now(tz=timezone.utc)
    current_month = current_date.strftime("%Y-%m")

    total_chars = 0
    entries = []
    log_file = Path("tts_usage.log")

    if log_file.exists():
        with log_file.open() as f:
            for line in f:
                if current_month in line:
                    # Extract character count from log line
                    # Format: YYYY-MM-DD HH:MM:SS | filename | voice | characters | running_total
                    try:
                        # Find the last number in the line (running total)
                        numbers = re.findall(r"\d+(?:\.\d+)?", line)
                        if numbers:
                            total_chars = int(
                                numbers[-2],
                            )  # Second to last is char count
                    except (IndexError, ValueError):
                        pass
                    entries.append(line.strip())

    return {
        "total_chars": total_chars,
        "current_month": current_month,
        "entries": entries,
    }


def log_usage(
    usage_logger: logging.Logger,
    filename: str,
    voice: str,
    char_count: int,
) -> None:
    """
    Log TTS usage with human-readable format including running monthly total.

    Args:
        usage_logger: Logger instance for usage tracking
        filename: Name of the file being processed
        voice: Voice used for TTS
        char_count: Number of characters processed
    """
    monthly_data = get_monthly_total()
    running_total = monthly_data["total_chars"] + char_count

    message = (
        f"{filename} | voice: {voice} | "
        f"characters: {char_count:,} | "
        f"monthly total: {running_total:,}"
    )
    usage_logger.info(message)


def split_text_into_chunks(text: str, max_bytes: int = 4500) -> list[str]:
    """
    Split text into chunks that don't exceed max_bytes when encoded as UTF-8.

    Tries to split at sentence boundaries to maintain readability.

    Args:
        text: The text to split
        max_bytes: Maximum byte size per chunk (default 4500, safe for 5000 limit)

    Returns:
        List of text chunks
    """
    chunks = []
    current_chunk = ""

    # Split by sentences (period, exclamation, question mark)
    sentences = re.split(r"(?<=[.!?])\s+", text)

    for sentence in sentences:
        test_chunk = current_chunk + sentence + " "
        if len(test_chunk.encode("utf-8")) <= max_bytes:
            current_chunk = test_chunk
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks


def combine_audio_chunks(
    audio_chunks: list[bytes],
    sample_rate: int = 24000,
) -> bytes:
    """
    Combine multiple raw audio chunks (LINEAR16 format) into a single WAV file.

    Args:
        audio_chunks: List of raw audio byte chunks
        sample_rate: Sample rate in Hz (default 24000)

    Returns:
        Combined audio as bytes in WAV format
    """
    # Parameters for WAV file
    num_channels = 1  # Mono
    sample_width = 2  # 16-bit = 2 bytes
    compression_type = "NONE"

    # Combine all audio data
    combined_audio = b"".join(audio_chunks)

    # Create WAV file in memory
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(num_channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(sample_rate)
        wav_file.setcomptype(compression_type, "not compressed")
        wav_file.writeframes(combined_audio)

    return wav_buffer.getvalue()


if __name__ == "__main__":
    logging.basicConfig(
        filename="logfile.txt",
        level=logging.ERROR,
        format="%(asctime)s %(message)s",
    )
    logger = logging.getLogger(__name__)
    usage_logger = initialize_usage_logger()

    # Load environment variables
    google_creds = getenv("GOOGLE_APPLICATION_CREDENTIALS")
    voice_name = getenv("TTS_VOICE_NAME", "en-US-Neural2-c")
    tts_model = getenv("TTS_MODEL", "chirp-hd")
    language_code = getenv("TTS_LANGUAGE_CODE", "en-US")

    # Validate credentials file exists
    if not google_creds or not Path(google_creds).exists():
        print(
            f"Error: GOOGLE_APPLICATION_CREDENTIALS not found. "
            f"Expected at: {google_creds}",
        )
        print("Please follow setup instructions in README.md")
        sys.exit(1)

    output_folder_path = Path(
        r"C:\Users\user\scripts\manual podcasts\misc",
    )
    archive_folder_path = Path(
        r"C:\Users\user\dev\TTS\archive",
    )
    input_folder_path = Path(
        r"C:\Users\user\dev\TTS\input",
    )

    # Ensure output and archive directories exist
    output_folder_path.mkdir(parents=True, exist_ok=True)
    archive_folder_path.mkdir(parents=True, exist_ok=True)

    # Initialize Google Cloud TTS client
    tts_client = texttospeech.TextToSpeechClient()

    input_paths = list(input_folder_path.glob("*.txt"))
    if input_paths:
        for filepath in input_paths:
            success = False
            with filepath.open("r", encoding="utf8") as file:
                filename = filepath.stem
                output_file_path = output_folder_path / f"{filename}.wav"
                if output_file_path.exists():
                    overwrite = input(
                        f"The file {output_file_path} already exists. "
                        f"Do you want to overwrite it? (y/n): ",
                    )
                    if overwrite.lower() != "y":
                        continue
                print(f"Starting {filename}")
                # thread for the spinner
                should_spin = Event()
                should_spin.set()
                spinner_thread = Thread(target=spinner, args=(should_spin,))
                spinner_thread.start()
                # slow task
                try:
                    text = file.read()
                    text = remove_citations(text)

                    # Split text into chunks if needed
                    text_chunks = split_text_into_chunks(text)
                    audio_chunks = []

                    # Prepare voice and audio config (reused for all chunks)
                    voice = texttospeech.VoiceSelectionParams(
                        language_code=language_code,
                        name=voice_name,
                    )

                    audio_config = texttospeech.AudioConfig(
                        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
                        sample_rate_hertz=24000,
                    )

                    # Synthesize each chunk
                    for chunk in text_chunks:
                        synthesis_input = texttospeech.SynthesisInput(text=chunk)

                        # Make the TTS request
                        response = tts_client.synthesize_speech(
                            input=synthesis_input,
                            voice=voice,
                            audio_config=audio_config,
                        )

                        audio_chunks.append(response.audio_content)

                    # Combine all audio chunks and save as WAV
                    combined_audio = combine_audio_chunks(audio_chunks)
                    with output_file_path.open("wb") as out:
                        out.write(combined_audio)

                    # Log usage
                    char_count = len(text)
                    log_usage(usage_logger, filename, voice_name, char_count)
                    success = True

                except FileNotFoundError as e:
                    print(f"File error while processing {filepath}: {e!s}")
                except PermissionError as e:
                    print(f"Permission error while processing {filepath}: {e!s}")
                except OSError as e:
                    print(f"OS error while processing {filepath}: {e!s}")
                except Exception:
                    logger.exception("Unexpected error while processing %s", filepath)
                    print(
                        f"Unexpected error occurred while processing {filepath}. "
                        f"Check logfile.txt for details.",
                    )
                # close spinner thread
                should_spin.clear()
                spinner_thread.join()
                print("Finished")
            if success:
                try:
                    shutil.move(
                        filepath,
                        str(Path(archive_folder_path) / Path(filepath).name),
                    )
                except (FileNotFoundError, PermissionError, OSError) as e:
                    print(f"Error moving file {filepath}: {e!s}")
        print("All files completed.")
    else:
        print("No text files found.")
