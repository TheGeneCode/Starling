"""
Batch-converts .txt files in the input directory to narrated .wav audio.

Removes citations, converts the text to speech using Google Cloud TTS, and saves the
resulting audio as .wav files in the output directory. Displays a spinner animation
during processing, handles file overwrites with user confirmation, logs errors and
usage, and moves processed files to an archive directory. A run that had failures ends
with a summary listing each failed file and why, and exits 1.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import re
import shutil
import sys
import time
import traceback
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
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
from starling.pronunciations import EMPTY_GUIDE, load_pronunciations
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
    from starling.pronunciations import PronunciationGuide

CONFIG = load_config()
USAGE_LOG_PATH = CONFIG.usage_log_path
ERROR_LOG_PATH = CONFIG.error_log_path

DEFAULT_SAMPLE_RATE_HERTZ: Final = 24000

ARCHIVE_FAILURE_REASON: Final = (
    "the .wav was written, but the input could not be moved to the archive, "
    "so the next run will read it again"
)
PAUSE_PROMPT: Final = "Press Enter to close this window."

OPEN_QUOTE: Final = "“"
CLOSE_QUOTE: Final = "”"

# Short-scale words a listener knows, smallest first. Currency is re-expressed in the
# largest one that fits, so the voice never says "thousand billion".
SCALE_EXPONENTS: Final = {
    "million": 6,
    "billion": 9,
    "trillion": 12,
    "quadrillion": 15,
    "quintillion": 18,
    "sextillion": 21,
    "septillion": 24,
    "octillion": 27,
    "nonillion": 30,
    "decillion": 33,
}
SCALED_CURRENCY_RE: Final = re.compile(
    r"\$(\d+(?:,\d{3})*(?:\.\d+)?)\s+(" + "|".join(SCALE_EXPONENTS) + r")\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReadOptions:
    """One `starling read` invocation's flags."""

    assume_yes: bool = False
    dry_run: bool = False
    confirm: bool = False
    input_dir: Path | None = None
    pause_on_error: bool = False


@dataclass(frozen=True, slots=True)
class DryRunEntry:
    """What `--dry-run` reports for one input file."""

    path: Path
    output_path: Path
    char_count: int
    chunk_count: int
    output_exists: bool


@dataclass(frozen=True, slots=True)
class FileResult:
    """What `process_file` did with one input file."""

    written: bool
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FileFailure:
    """One input file `read` could not finish, for the end-of-run summary."""

    path: Path
    reason: str


def spinner(should_spin: Event) -> None:
    """
    Display a spinning animation on the console while a task is being executed.

    Args: should_spin (Event): An Event object that controls whether the spinner
    animation should continue spinning or stop.
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


def scale_currency(match: re.Match[str]) -> str:
    """
    Re-express "$<amount> <scale word>" with the largest scale word that fits.

    "$1,300 million" -> "1.3 billion dollars"; "$3 trillion" -> "3 trillion dollars".
    Amounts past the largest word stay in it ("1000 decillion dollars"). Decimal, not
    float, so no amount overflows to "inf" or picks up binary rounding noise.
    """
    digits = match.group(1).replace(",", "")
    scales = [("", 0), *SCALE_EXPONENTS.items()]
    # Room for every digit, the widest shift and the tenths place: only quantize rounds.
    with localcontext(prec=len(digits) + max(SCALE_EXPONENTS.values()) + 1):
        total = Decimal(digits).scaleb(SCALE_EXPONENTS[match.group(2).lower()])
        index = max(i for i, (_, exp) in enumerate(scales) if i == 0 or total >= 10**exp)
        rounded = total.scaleb(-scales[index][1]).quantize(Decimal("0.1"))
        # Rounding can carry 999.96 billion to 1000.0; say "1 trillion" instead.
        if 0 < index < len(scales) - 1 and rounded >= 1000:
            index += 1
            rounded = total.scaleb(-scales[index][1]).quantize(Decimal("0.1"))
    val_fmt = f"{rounded:f}".removesuffix(".0")
    return " ".join(part for part in (val_fmt, scales[index][0], "dollars") if part)


def convert_numbers_to_words(text: str) -> str:
    """Convert numbers to words in the text, handling currency scaling and formatting."""
    # 1. Currency with a scale word: $1,300 million -> 1.3 billion dollars
    text = SCALED_CURRENCY_RE.sub(scale_currency, text)

    # 2. Handle simple currency ($1,234.56 -> one thousand... dollars and fifty-six cents)
    def currency_to_words(match: re.Match[str]) -> str:
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
    def number_to_words(match: re.Match[str]) -> str:
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


def prepare_text(raw: str, guide: PronunciationGuide = EMPTY_GUIDE) -> str:
    """
    Turn an article's raw text into exactly what `read` synthesizes and bills.

    The guide runs before number conversion so its keys match the article as written.
    `process_file` and `plan_dry_run` both call this, so a dry run's count is the bill.
    """
    return convert_numbers_to_words(guide.apply(remove_citations(raw)))


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


def confirm_synthesis(*, prompt: Callable[[str], str] = input) -> bool:
    """
    Ask whether to proceed from the dry-run preview to the real, billed run.

    Mirrors confirm_overwrite's acceptance rule exactly: only "y" (any case)
    proceeds, so an empty line, Ctrl-D's empty string, or anything else is a no.
    """
    answer = prompt("Proceed with synthesis? (y/n): ")
    return answer.lower() == "y"


def print_failure_summary(failures: Sequence[FileFailure], total: int) -> None:
    """Print the end-of-run list of failed files, so an error is not lost mid-scroll."""
    print()
    print(f"{len(failures)} of {total} file(s) failed:")
    for failure in failures:
        print(f"  {failure.path.name}: {failure.reason}")
    print("Failed files stay in the input directory; the next `starling read` retries them.")


def wait_for_enter(*, prompt: Callable[[str], str] = input) -> None:
    """
    Hold the console open until the user presses Enter.

    EOF (no stdin attached) returns at once rather than raising, so a piped or
    detached run never hangs or crashes here.
    """
    with contextlib.suppress(EOFError):
        prompt(f"\n{PAUSE_PROMPT} ")


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


def ends_inside_quotation(text: str, *, inside: bool = False) -> bool:
    """
    Return whether `text` ends between a “ and its ”, given the state it started in.

    Curly quotes only: a straight " cannot say whether it opens or closes, and an inch
    mark would flip the state. A “ with no ” before the next “ (a quotation continued
    into the next paragraph, news style) stays open until a ” arrives.
    """
    last_open = text.rfind(OPEN_QUOTE)
    last_close = text.rfind(CLOSE_QUOTE)
    if last_open == last_close:  # both -1: no curly quote at all
        return inside
    return last_open > last_close


def group_sentences_by_quotation(sentences: Sequence[str]) -> list[list[str]]:
    """
    Group consecutive sentences so no group ends inside a quotation.

    Chirp 3 HD, sent a chunk that ends in an unclosed “, can read a quoted phrase as
    "quote quote quote..." instead of its words (backlog #10), so chunk boundaries
    go only between groups.
    """
    groups: list[list[str]] = []
    current: list[str] = []
    inside = False
    for sentence in sentences:
        current.append(sentence)
        inside = ends_inside_quotation(sentence, inside=inside)
        if not inside:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def split_text_into_chunks(text: str, max_bytes: int = 4500) -> list[str]:
    """
    Split text into chunks that don't exceed max_bytes when encoded as UTF-8.

    Splits at sentence boundaries outside quotations. A quotation that alone exceeds
    max_bytes falls back to its sentence boundaries.

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
    pieces: list[str] = []
    for group in group_sentences_by_quotation(sentences):
        joined = " ".join(group)
        # Fits alone, trailing space included; otherwise fall back to its sentences.
        pieces.extend([joined] if len(joined.encode("utf-8")) < max_bytes else group)

    for sentence in pieces:
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
    configured = (config.voice_name,) if config.voice_mode is VoiceMode.FIXED else config.voice_pool
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
    guide: PronunciationGuide = EMPTY_GUIDE,
) -> FileResult:
    """
    Synthesize one article.

    `written` is True only when the .wav was written and logged; `error` carries the
    message printed for a failure.
    """
    output_path = config.output_dir / f"{filepath.stem}.wav"
    if not confirm_overwrite(output_path, assume_yes=options.assume_yes):
        return FileResult(written=False)

    print(f"Starting {filepath.stem}")
    print(format_monthly_total(get_monthly_total(config.usage_log_path)))

    error: str | None = None
    with spinner_running():
        try:
            # The read is inside the try on purpose: a locked or vanished file is a
            # per-file error, not a reason to abandon the rest of the batch.
            text = prepare_text(filepath.read_text(encoding="utf8"), guide)
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
        except FileNotFoundError as e:
            error = f"File error while processing {filepath}: {e!s}"
            print(error)
        except PermissionError as e:
            error = f"Permission error while processing {filepath}: {e!s}"
            print(error)
        except OSError as e:
            error = f"OS error while processing {filepath}: {e!s}"
            print(error)
        except Exception:
            logger.exception("Unexpected error while processing %s", filepath)
            error = (
                f"Unexpected error occurred while processing {filepath}. "
                f"Check {config.error_log_path} for details."
            )
            print(error)
    print("Finished")
    return FileResult(written=error is None, error=error)


def _configured_voice_names(config: StarlingConfig) -> tuple[str, ...]:
    """Configured voice names, unvalidated — a dry run never contacts Google."""  # noqa: D401
    return (config.voice_name,) if config.voice_mode is VoiceMode.FIXED else config.voice_pool


def plan_dry_run(
    input_paths: Sequence[Path],
    config: StarlingConfig,
    *,
    guide: PronunciationGuide = EMPTY_GUIDE,
) -> list[DryRunEntry]:
    """Measure every input file the way `read` would bill it, without calling the API."""
    entries: list[DryRunEntry] = []
    for path in input_paths:
        try:
            text = prepare_text(path.read_text(encoding="utf8"), guide)
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
        f"After this run the month would total {monthly['total_chars'] + total:,} characters.",
    )
    print(
        pricing_notice(
            [model_family(name) for name in _configured_voice_names(config)],
        ),
    )


def _load_guide_or_report(config: StarlingConfig) -> PronunciationGuide | None:
    """Load the pronunciation guide and announce it; print the error and return None if bad."""
    try:
        guide = load_pronunciations(
            config.pronunciations_path,
            required=config.pronunciations_required,
        )
    except ConfigError as exc:
        print(f"Error: {exc}")
        return None
    if guide:
        entries = "entry" if len(guide) == 1 else "entries"
        print(f"Pronunciation guide: {len(guide)} {entries}.")
    return guide


def _preview_and_confirm(
    input_paths: Sequence[Path],
    config: StarlingConfig,
    guide: PronunciationGuide,
    options: ReadOptions,
) -> bool:
    """Show the dry-run report and ask to proceed; False means the user cancelled."""
    print_dry_run(
        plan_dry_run(input_paths, config, guide=guide),
        config,
        assume_yes=options.assume_yes,
    )
    print()
    if not confirm_synthesis():
        print(
            "Cancelled. Nothing was synthesized; your files are still in the input directory.",
        )
        return False
    print()
    return True


def _run_read(config: StarlingConfig | None, options: ReadOptions) -> int:
    """Run the pipeline proper; `run_read` wraps it with the optional pause."""
    config = config if config is not None else load_config()

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

    # Before the dry-run branch, so a dry run validates the guide and a bad guide
    # fails before any credential check or API call.
    guide = _load_guide_or_report(config)
    if guide is None:
        return 1

    if options.dry_run:
        print_dry_run(
            plan_dry_run(input_paths, config, guide=guide),
            config,
            assume_yes=options.assume_yes,
        )
        return 0

    if options.confirm and not _preview_and_confirm(input_paths, config, guide, options):
        return 0

    try:
        require_credentials(config)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1

    configure_logging("ERROR", log_file=config.error_log_path, console="none")
    logger = get_logger(__name__)
    usage_logger = initialize_usage_logger(config.usage_log_path)

    try:
        client = texttospeech.TextToSpeechClient()
        voice_pool = resolve_voice_pool(config, client)
    except (UnknownVoiceError, ConfigError) as exc:
        print(f"Error: {exc}")
        return 1
    except (DefaultCredentialsError, GoogleAPICallError) as exc:
        print(f"Error: could not reach Google Text-to-Speech to check voices: {exc}")
        return 1

    print(pricing_notice([model_family(name) for name in voice_pool]))

    failures: list[FileFailure] = []
    for filepath in input_paths:
        result = process_file(
            filepath,
            client=client,
            config=config,
            voice_pool=voice_pool,
            usage_logger=usage_logger,
            logger=logger,
            options=options,
            guide=guide,
        )
        if result.error is not None:
            failures.append(FileFailure(filepath, result.error))
        elif result.written and not archive_file(filepath, config.archive_dir):
            failures.append(FileFailure(filepath, ARCHIVE_FAILURE_REASON))

    if failures:
        print_failure_summary(failures, len(input_paths))
        return 1
    print("All files completed.")
    return 0


def run_read(
    config: StarlingConfig | None = None,
    options: ReadOptions | None = None,
    *,
    prompt: Callable[[str], str] = input,
) -> int:
    """
    Run the article-to-speech pipeline. Returns a process exit code.

    With `options.pause_on_error`, any non-zero exit (a failed file, a config or
    credentials error, or an unexpected crash, printed as a traceback) waits for Enter
    first: `starling capture` runs the reader in a console that closes on exit, and the
    error would close with it.
    """
    options = options if options is not None else ReadOptions()
    try:
        code = _run_read(config, options)
    except Exception:
        if not options.pause_on_error:
            raise
        traceback.print_exc()
        code = 1
    if code != 0 and options.pause_on_error:
        wait_for_enter(prompt=prompt)
    return code


def run_usage(config: StarlingConfig | None = None) -> int:
    """Print this month's character total — the same line `read` prints per file."""
    config = config if config is not None else load_config()
    print(format_monthly_total(get_monthly_total(config.usage_log_path)))
    return 0


if __name__ == "__main__":
    sys.exit(run_read())
