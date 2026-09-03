"""Processes all .txt files in the specified input directory by removing citations, converting the text to speech using Google Cloud TTS, and saving the resulting audio as .wav files in the output directory. Displays a spinner animation during processing, handles file overwrites with user confirmation, logs errors and usage, and moves processed files to an archive directory."""

from __future__ import annotations

import contextlib
import io
import itertools
import re
import shutil
import sys
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Final

from genekit.logging import configure_logging, dedicated_file_logger, get_logger
from google.api_core.exceptions import GoogleAPICallError
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import texttospeech
from num2words import num2words

from starling.config import (
    ConfigError,
    VoiceMode,
    ensure_directories,
    load_config,
    require_credentials,
)
from starling.voices import (
    UnknownVoiceError,
    fetch_voices,
    model_family,
    pricing_notice,
    select_voice,
    validate_voice_names,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable, Iterator, Sequence

    from starling.config import StarlingConfig

# from kittentts import KittenTTS

CONFIG = load_config()
USAGE_LOG_PATH = CONFIG.usage_log_path
ERROR_LOG_PATH = CONFIG.error_log_path

DEFAULT_SAMPLE_RATE_HERTZ: Final = 24000


@dataclass(frozen=True, slots=True)
class ReadOptions:
    """One `starling read` invocation's flags."""

    assume_yes: bool = False
    dry_run: bool = False
    input_dir: Path | None = None


@dataclass(frozen=True, slots=True)
class DryRunEntry:
    """What `--dry-run` reports for one input file."""

    path: Path
    output_path: Path
    char_count: int
    chunk_count: int
    output_exists: bool


def spinner(should_spin: Event) -> None:
    """
    Display a spinning animation on the console while a task is being executed.

    Args: should_spin (Event): An Event object that controls whether the spinner animation should continue spinning or stop.
    """
    chars = itertools.cycle(r"-\|/")
    while should_spin.is_set():
        char = next(chars)
        print(f"Speaking... {char}", end="\r")
        time.sleep(0.1)


def remove_citations(text: str) -> str:
    # Remove traditional citations (e.g., (Author, 2020))
    citations_regex = r"\([^\)]+(?:,\s*\d{4}(?:[a-zA-Z]?)?(?:,\s*p\.\s*\d+)?)+\)"
    text = re.sub(citations_regex, "", text)
    # Remove footnote markers (e.g., [1], [2])
    footnotes_regex = r"\[\d+\]"
    return re.sub(footnotes_regex, "", text)


def convert_numbers_to_words(text: str) -> str:
    """Convert numbers to words in the text, handling currency scaling and formatting."""

    # 1. Handle "X million/billion" currency scaling
    # Pattern: $1,300 million -> 1.3 billion dollars
    def scale_currency(match):
        val_str = match.group(1).replace(",", "")
        unit = match.group(2).lower()
        val = float(val_str)

        multipliers = {
            "million": 1e6,
            "billion": 1e9,
            "trillion": 1e12,
        }

        if unit in multipliers:
            total_val = val * multipliers[unit]

            # Determine new unit
            if total_val >= 1e9:
                new_val = total_val / 1e9
                new_unit = "billion"
            elif total_val >= 1e6:
                new_val = total_val / 1e6
                new_unit = "million"
            else:
                new_val = total_val
                new_unit = ""  # Should be rare for million+ inputs

            # Format: 1.3 billion dollars
            if new_val.is_integer():
                val_fmt = f"{int(new_val)}"
            else:
                val_fmt = f"{new_val:.1f}".rstrip("0").rstrip(".")

            return f"{val_fmt} {new_unit} dollars".strip()

        return match.group(0)

    # Regex for $X million/billion
    text = re.sub(
        r"\$(\d+(?:,\d{3})*(?:\.\d+)?)\s+(million|billion|trillion)",
        scale_currency,
        text,
        flags=re.IGNORECASE,
    )

    # 2. Handle simple currency ($1,234.56 -> one thousand... dollars and fifty-six cents)
    def currency_to_words(match):
        val_str = match.group(1).replace(",", "")
        try:
            val = float(val_str)
            words = num2words(val, to="currency", currency="USD")
            # Remove ", zero cents" if present
            words = words.removesuffix(", zero cents")
            return words.replace(",", "")  # Remove commas in words
        except Exception:
            return match.group(0)

    # Regex for $X (where X has at least one comma)
    text = re.sub(r"\$(\d{1,3}(?:,\d{3})+(?:\.\d+)?)", currency_to_words, text)

    # 3. Handle plain numbers with commas (1,234 -> one thousand...)
    def number_to_words(match):
        val_str = match.group(0).replace(",", "")
        try:
            val = int(val_str)  # num2words handles ints best for cardinal
            return num2words(val).replace(",", "")
        except Exception:
            try:
                val = float(val_str)
                return num2words(val).replace(",", "")
            except Exception:
                return match.group(0)

    # Regex for X,XXX... (at least one comma)
    return re.sub(
        r"(?<![\$\d])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])",
        number_to_words,
        text,
    )


def initialize_usage_logger(usage_log_path: Path | None = None) -> logging.Logger:
    """
    Initialize and return a logger for TTS usage tracking.

    Args:
        usage_log_path: Override for the usage log path. Defaults to USAGE_LOG_PATH.
    """
    path = usage_log_path if usage_log_path is not None else USAGE_LOG_PATH
    return dedicated_file_logger(
        "tts_usage",
        path,
        fmt="%(asctime)s | %(message)s",
    )


def get_monthly_total(usage_log_path: Path | None = None) -> dict:
    """
    Parse the usage log and return character count and details for current month.

    Args:
        usage_log_path: Override for the usage log path. Defaults to USAGE_LOG_PATH.

    Returns:
        dict: Contains 'total_chars', 'current_month', 'entries' (list of log entries)
    """
    path = usage_log_path if usage_log_path is not None else USAGE_LOG_PATH
    current_date = datetime.now(tz=UTC)
    current_month = current_date.strftime("%Y-%m")

    total_chars = 0
    entries = []

    if path.exists():
        with path.open() as f:
            for line in f:
                if current_month in line:
                    entries.append(line.strip())
                    # Prefer parsing the explicit 'monthly total' field (running total)
                    m = re.search(r"monthly total:\s*([\d,]+)", line, re.IGNORECASE)
                    if m:
                        with contextlib.suppress(ValueError):
                            total_chars = int(m.group(1).replace(",", ""))

    return {
        "total_chars": total_chars,
        "current_month": current_month,
        "entries": entries,
    }


def format_monthly_total(monthly: dict) -> str:
    """
    Render the month-to-date usage line that `read` prints before every file.

    `usage` prints this exact string, so the two commands can never disagree.
    """
    return (
        f"[{monthly['current_month']}] Total characters logged this month: "
        f"{monthly['total_chars']:,} | {monthly['total_chars'] / 1000000:.0%}"
    )


@contextlib.contextmanager
def spinner_running() -> Iterator[None]:
    """Run the console spinner for the duration of the block, always joining the thread."""
    should_spin = Event()
    should_spin.set()
    spinner_thread = Thread(target=spinner, args=(should_spin,))
    spinner_thread.start()
    try:
        yield
    finally:
        should_spin.clear()
        spinner_thread.join()


def confirm_overwrite(
    output_path: Path,
    *,
    assume_yes: bool = False,
    prompt: Callable[[str], str] = input,
) -> bool:
    """
    Return True when synthesis should proceed for this output path.

    Preserves the original prompt text and its `.lower() != "y"` acceptance rule exactly;
    `assume_yes` (the --yes/--overwrite flag) skips the prompt entirely.
    """
    if not output_path.exists():
        return True
    if assume_yes:
        return True
    answer = prompt(
        f"The file {output_path} already exists. Do you want to overwrite it? (y/n): ",
    )
    return answer.lower() == "y"


def log_usage(
    usage_logger: logging.Logger,
    filename: str,
    voice: str,
    char_count: int,
    usage_log_path: Path | None = None,
) -> None:
    """
    Log TTS usage with human-readable format including running monthly total.

    Args:
        usage_logger: Logger instance for usage tracking
        filename: Name of the file being processed
        voice: Voice used for TTS
        char_count: Number of characters processed
        usage_log_path: Override for the usage log path. Defaults to USAGE_LOG_PATH.
    """
    monthly_data = get_monthly_total(usage_log_path)
    running_total = monthly_data["total_chars"] + char_count

    message = (
        f"{filename} | voice: {voice} | "
        f"characters: {char_count:,} | "
        f"monthly total: {running_total:,}"
    )
    usage_logger.info(message)
    # Ensure the log is written to disk
    for handler in usage_logger.handlers:
        handler.flush()


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


def resolve_voice_pool(
    config: StarlingConfig,
    client: texttospeech.TextToSpeechClient,
) -> tuple[str, ...]:
    """
    Resolve the configured voice(s) against Google's live catalog.

    Raises UnknownVoiceError / ConfigError for a bad name, and
    DefaultCredentialsError / GoogleAPICallError when the catalog is unreachable.
    ListVoices is not billed, so this is free early validation.
    """
    configured = (
        (config.voice_name,)
        if config.voice_mode is VoiceMode.FIXED
        else config.voice_pool
    )
    return validate_voice_names(configured, fetch_voices(client, config.language_code))


def synthesize_text(
    client: texttospeech.TextToSpeechClient,
    text: str,
    *,
    voice_name: str,
    language_code: str,
    sample_rate: int = DEFAULT_SAMPLE_RATE_HERTZ,
) -> bytes:
    """Chunk `text`, synthesize every chunk with one voice, and return one WAV blob."""
    voice = texttospeech.VoiceSelectionParams(
        language_code=language_code,
        name=voice_name,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,
    )
    audio_chunks = [
        client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=chunk),
            voice=voice,
            audio_config=audio_config,
        ).audio_content
        for chunk in split_text_into_chunks(text)
    ]
    return combine_audio_chunks(audio_chunks, sample_rate)


def archive_file(filepath: Path, archive_dir: Path) -> bool:
    """Move a processed input file into the archive. Returns False on failure."""
    try:
        shutil.move(str(filepath), str(Path(archive_dir) / filepath.name))
    except (FileNotFoundError, PermissionError, OSError) as e:
        print(f"Error moving file {filepath}: {e!s}")
        return False
    return True


def process_file(
    filepath: Path,
    *,
    client: texttospeech.TextToSpeechClient,
    config: StarlingConfig,
    voice_pool: Sequence[str],
    usage_logger: logging.Logger,
    logger: logging.Logger,
    options: ReadOptions,
) -> bool:
    """Synthesize one article. Returns True only when the .wav was written and logged."""
    output_path = config.output_dir / f"{filepath.stem}.wav"
    if not confirm_overwrite(output_path, assume_yes=options.assume_yes):
        return False

    print(f"Starting {filepath.stem}")
    print(format_monthly_total(get_monthly_total(config.usage_log_path)))

    success = False
    with spinner_running():
        try:
            # The read is inside the try on purpose: a locked or vanished file is a
            # per-file error, not a reason to abandon the rest of the batch.
            text = convert_numbers_to_words(remove_citations(filepath.read_text(encoding="utf8")))
            selected_voice = select_voice(config, voice_pool)
            print(f"Using voice: {selected_voice}")
            audio = synthesize_text(
                client,
                text,
                voice_name=selected_voice,
                language_code=config.language_code,
            )
            output_path.write_bytes(audio)
            log_usage(
                usage_logger,
                filepath.stem,
                selected_voice,
                len(text),
                config.usage_log_path,
            )
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
                f"Check {config.error_log_path} for details.",
            )
    print("Finished")
    return success


def _configured_voice_names(config: StarlingConfig) -> tuple[str, ...]:
    """Configured voice names, unvalidated — a dry run never contacts Google."""  # noqa: D401
    return (
        (config.voice_name,)
        if config.voice_mode is VoiceMode.FIXED
        else config.voice_pool
    )


def plan_dry_run(
    input_paths: Sequence[Path],
    config: StarlingConfig,
) -> list[DryRunEntry]:
    """Measure every input file the way `read` would bill it, without calling the API."""
    entries: list[DryRunEntry] = []
    for path in input_paths:
        try:
            text = convert_numbers_to_words(remove_citations(path.read_text(encoding="utf8")))
        except OSError as e:
            print(f"File error while processing {path}: {e!s}")
            continue
        output_path = config.output_dir / f"{path.stem}.wav"
        entries.append(
            DryRunEntry(
                path=path,
                output_path=output_path,
                char_count=len(text),
                chunk_count=len(split_text_into_chunks(text)),
                output_exists=output_path.exists(),
            ),
        )
    return entries


def print_dry_run(
    entries: Sequence[DryRunEntry],
    config: StarlingConfig,
    *,
    assume_yes: bool = False,
) -> None:
    """Print the dry-run report. Never prompts, never calls Google, never moves a file."""
    print("Dry run — nothing is synthesized and no Google API calls are made.")
    print()
    for entry in entries:
        flag = "*" if entry.output_exists else " "
        chunks = "chunk" if entry.chunk_count == 1 else "chunks"
        print(
            f"  {flag} {entry.path.name}  {entry.char_count:,} characters, "
            f"{entry.chunk_count} {chunks} -> {entry.output_path}",
        )
    if any(entry.output_exists for entry in entries):
        note = (
            "would be overwritten (--yes)"
            if assume_yes
            else "already exists; `read` would prompt before overwriting"
        )
        print()
        print(f"  * output {note}.")

    total = sum(entry.char_count for entry in entries)
    monthly = get_monthly_total(config.usage_log_path)
    print()
    print(f"{len(entries)} file(s), {total:,} characters would be billed.")
    print(format_monthly_total(monthly))
    print(
        f"After this run the month would total "
        f"{monthly['total_chars'] + total:,} characters.",
    )
    print(
        pricing_notice(
            [model_family(name) for name in _configured_voice_names(config)],
        ),
    )


def run_read(
    config: StarlingConfig | None = None,
    options: ReadOptions | None = None,
) -> int:
    """Run the article-to-speech pipeline. Returns a process exit code."""
    config = config if config is not None else load_config()
    options = options if options is not None else ReadOptions()

    try:
        ensure_directories(config)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1

    input_dir = options.input_dir if options.input_dir is not None else config.input_dir
    input_paths = sorted(input_dir.glob("*.txt"))
    if not input_paths:
        print("No text files found.")
        return 0

    if options.dry_run:
        print_dry_run(
            plan_dry_run(input_paths, config),
            config,
            assume_yes=options.assume_yes,
        )
        return 0

    try:
        require_credentials(config)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1

    configure_logging("ERROR", log_file=config.error_log_path, console="none")
    logger = get_logger(__name__)
    usage_logger = initialize_usage_logger(config.usage_log_path)

    client = texttospeech.TextToSpeechClient()
    try:
        voice_pool = resolve_voice_pool(config, client)
    except (UnknownVoiceError, ConfigError) as exc:
        print(f"Error: {exc}")
        return 1
    except (DefaultCredentialsError, GoogleAPICallError) as exc:
        print(f"Error: could not reach Google Text-to-Speech to check voices: {exc}")
        return 1

    print(pricing_notice([model_family(name) for name in voice_pool]))

    for filepath in input_paths:
        if process_file(
            filepath,
            client=client,
            config=config,
            voice_pool=voice_pool,
            usage_logger=usage_logger,
            logger=logger,
            options=options,
        ):
            archive_file(filepath, config.archive_dir)

    print("All files completed.")
    return 0


def run_usage(config: StarlingConfig | None = None) -> int:
    """Print this month's character total — the same line `read` prints per file."""
    config = config if config is not None else load_config()
    print(format_monthly_total(get_monthly_total(config.usage_log_path)))
    return 0


if __name__ == "__main__":
    sys.exit(run_read())
