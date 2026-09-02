"""
Behavioral tests for starling.reader's Phase 3a pipeline extraction.

Covers the option/report dataclasses, the small pure helpers (format_monthly_total,
spinner_running, confirm_overwrite, archive_file, synthesize_text, resolve_voice_pool),
and the orchestration functions (process_file, plan_dry_run, print_dry_run, run_read,
run_usage). No test constructs a real TextToSpeechClient, makes a network call, or needs
real credentials.
"""

from __future__ import annotations

import io
import threading
import wave
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import GoogleAPICallError

from starling import reader
from starling.config import StarlingConfig, VoiceMode, ensure_directories

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_config(tmp_path: Path, fake_credentials: Path) -> StarlingConfig:
    """A StarlingConfig whose every path lives under tmp_path, with dirs created."""  # noqa: D401
    config = StarlingConfig(
        home_dir=tmp_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        archive_dir=tmp_path / "archive",
        credentials_path=fake_credentials,
        language_code="en-US",
        voice_mode=VoiceMode.FIXED,
        voice_name="en-US-Chirp3-HD-Aoede",
        voice_pool=("en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Puck"),
        usage_log_path=tmp_path / "logs" / "usage.log",
        error_log_path=tmp_path / "logs" / "errors.log",
    )
    ensure_directories(config)
    return config


# ---------------------------------------------------------------------------
# confirm_overwrite
# ---------------------------------------------------------------------------


def test_confirm_overwrite_missing_output_never_prompts(tmp_path: Path) -> None:
    """Test that a nonexistent output path returns True without prompting."""
    output_path = tmp_path / "missing.wav"

    def _raise(_message: str) -> str:
        raise AssertionError("prompt should not be called")

    assert reader.confirm_overwrite(output_path, prompt=_raise) is True


def test_confirm_overwrite_assume_yes_never_prompts(tmp_path: Path) -> None:
    """Test that assume_yes=True returns True without prompting even if output exists."""
    output_path = tmp_path / "existing.wav"
    output_path.write_bytes(b"")

    def _raise(_message: str) -> str:
        raise AssertionError("prompt should not be called")

    assert reader.confirm_overwrite(output_path, assume_yes=True, prompt=_raise) is True


@pytest.mark.parametrize("answer", ["y", "Y"])
def test_confirm_overwrite_accepts_y_case_insensitively(
    tmp_path: Path, answer: str
) -> None:
    """Test that a 'y' or 'Y' answer confirms the overwrite."""
    output_path = tmp_path / "existing.wav"
    output_path.write_bytes(b"")

    assert reader.confirm_overwrite(output_path, prompt=lambda _msg: answer) is True


@pytest.mark.parametrize("answer", ["n", "", "yes"])
def test_confirm_overwrite_rejects_non_y_answers(tmp_path: Path, answer: str) -> None:
    """Test that only exact-match 'y' (case-insensitive) confirms; everything else declines."""
    output_path = tmp_path / "existing.wav"
    output_path.write_bytes(b"")

    assert reader.confirm_overwrite(output_path, prompt=lambda _msg: answer) is False


def test_confirm_overwrite_prompt_text_is_unchanged(tmp_path: Path) -> None:
    """Test that the prompt text sent to the user is byte-identical to the original."""
    output_path = tmp_path / "existing.wav"
    output_path.write_bytes(b"")
    captured: list[str] = []

    def _capture(message: str) -> str:
        captured.append(message)
        return "y"

    reader.confirm_overwrite(output_path, prompt=_capture)

    assert captured == [
        f"The file {output_path} already exists. Do you want to overwrite it? (y/n): ",
    ]


# ---------------------------------------------------------------------------
# spinner_running
# ---------------------------------------------------------------------------


def test_spinner_running_joins_thread_on_normal_exit() -> None:
    """Test that no new thread survives a normal exit from the context manager."""
    before = set(threading.enumerate())
    with reader.spinner_running():
        pass
    after = set(threading.enumerate())
    assert after <= before


def test_spinner_running_joins_thread_when_body_raises() -> None:
    """Test that the spinner thread is still joined when the body raises."""
    before = set(threading.enumerate())
    with pytest.raises(ValueError, match="boom"), reader.spinner_running():
        raise ValueError("boom")
    after = set(threading.enumerate())
    assert after <= before


# ---------------------------------------------------------------------------
# synthesize_text
# ---------------------------------------------------------------------------


def test_synthesize_text_one_request_per_chunk(
    monkeypatch: pytest.MonkeyPatch, fake_tts_client: MagicMock
) -> None:
    """Test that synthesize_text issues one synthesize_speech call per text chunk."""
    monkeypatch.setattr(reader, "split_text_into_chunks", lambda _text: ["a", "b", "c"])
    fake_tts_client.synthesize_speech.return_value = SimpleNamespace(
        audio_content=b"\x00\x01"
    )

    reader.synthesize_text(
        fake_tts_client,
        "irrelevant",
        voice_name="en-US-Chirp3-HD-Aoede",
        language_code="en-US",
    )

    assert fake_tts_client.synthesize_speech.call_count == 3


def test_synthesize_text_returns_parseable_wav(
    monkeypatch: pytest.MonkeyPatch, fake_tts_client: MagicMock
) -> None:
    """Test that synthesize_text's output opens as a WAV with the right framerate/channels."""
    monkeypatch.setattr(
        reader, "split_text_into_chunks", lambda _text: ["chunk one", "chunk two"]
    )
    fake_tts_client.synthesize_speech.side_effect = [
        SimpleNamespace(audio_content=b"\x01\x00"),
        SimpleNamespace(audio_content=b"\x02\x00"),
    ]

    wav_bytes = reader.synthesize_text(
        fake_tts_client,
        "irrelevant",
        voice_name="en-US-Chirp3-HD-Aoede",
        language_code="en-US",
    )

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnchannels() == 1
        assert wav_file.readframes(2) == b"\x01\x00\x02\x00"


def test_synthesize_text_passes_voice_and_language(fake_tts_client: MagicMock) -> None:
    """Test that the voice name and language code reach the synthesize_speech call."""
    fake_tts_client.synthesize_speech.return_value = SimpleNamespace(
        audio_content=b"\x00\x00"
    )

    reader.synthesize_text(
        fake_tts_client,
        "Short sentence.",
        voice_name="en-US-Chirp3-HD-Puck",
        language_code="en-GB",
    )

    _args, kwargs = fake_tts_client.synthesize_speech.call_args
    assert kwargs["voice"].name == "en-US-Chirp3-HD-Puck"
    assert kwargs["voice"].language_code == "en-GB"


# ---------------------------------------------------------------------------
# resolve_voice_pool
# ---------------------------------------------------------------------------


def test_resolve_voice_pool_fixed_mode_returns_one_canonical_name(
    tmp_config: StarlingConfig, fake_tts_client: MagicMock
) -> None:
    """Test that FIXED mode resolves a single voice name to its canonical spelling."""
    config = replace(
        tmp_config, voice_mode=VoiceMode.FIXED, voice_name="EN-us-chirp3-hd-aoede"
    )

    result = reader.resolve_voice_pool(config, fake_tts_client)

    assert result == ("en-US-Chirp3-HD-Aoede",)


def test_resolve_voice_pool_random_mode_returns_whole_pool(
    tmp_config: StarlingConfig, fake_tts_client: MagicMock
) -> None:
    """Test that RANDOM mode resolves and returns the whole configured pool, in order."""
    config = replace(
        tmp_config,
        voice_mode=VoiceMode.RANDOM,
        voice_pool=("en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Puck"),
    )

    result = reader.resolve_voice_pool(config, fake_tts_client)

    assert result == ("en-US-Chirp3-HD-Aoede", "en-US-Chirp3-HD-Puck")


def test_resolve_voice_pool_unknown_name_raises(
    tmp_config: StarlingConfig, fake_tts_client: MagicMock
) -> None:
    """Test that an unrecognized voice name in the pool raises UnknownVoiceError."""
    config = replace(
        tmp_config, voice_mode=VoiceMode.RANDOM, voice_pool=("en-US-Nope-Z",)
    )

    with pytest.raises(reader.UnknownVoiceError):
        reader.resolve_voice_pool(config, fake_tts_client)


# ---------------------------------------------------------------------------
# archive_file
# ---------------------------------------------------------------------------


def test_archive_file_moves_input_into_archive(tmp_path: Path) -> None:
    """Test that archive_file moves the file and reports success."""
    input_dir = tmp_path / "input"
    archive_dir = tmp_path / "archive"
    input_dir.mkdir()
    archive_dir.mkdir()
    filepath = input_dir / "a.txt"
    filepath.write_text("hello", encoding="utf-8")

    assert reader.archive_file(filepath, archive_dir) is True
    assert (archive_dir / "a.txt").exists()
    assert not filepath.exists()


def test_archive_file_reports_failure_without_raising(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a move failure returns False and prints an error instead of raising."""
    filepath = tmp_path / "a.txt"
    filepath.write_text("hello", encoding="utf-8")

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(reader.shutil, "move", _raise)

    result = reader.archive_file(filepath, tmp_path / "archive")

    assert result is False
    assert "Error moving file" in capsys.readouterr().out


def test_archive_file_missing_archive_dir_returns_false_without_raising(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a nonexistent (never-created) archive directory fails safely, not raises."""
    filepath = tmp_path / "a.txt"
    filepath.write_text("hello", encoding="utf-8")
    missing_archive_dir = tmp_path / "does_not_exist"

    result = reader.archive_file(filepath, missing_archive_dir)

    assert result is False
    assert "Error moving file" in capsys.readouterr().out
    assert filepath.exists()


# ---------------------------------------------------------------------------
# process_file
# ---------------------------------------------------------------------------


def test_process_file_happy_path_writes_wav_and_logs_usage(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    isolated_logging: None,
) -> None:
    """Test that a successful synthesis writes the .wav and logs usage with the stem."""
    fake_tts_client.synthesize_speech.return_value = SimpleNamespace(
        audio_content=b"\x00\x01"
    )
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    usage_logger = reader.initialize_usage_logger(tmp_config.usage_log_path)

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=usage_logger,
        logger=MagicMock(),
        options=reader.ReadOptions(),
    )

    assert result is True
    assert (tmp_config.output_dir / "article.wav").exists()
    log_content = tmp_config.usage_log_path.read_text(encoding="utf-8")
    assert "article" in log_content
    assert "monthly total:" in log_content


def test_process_file_declined_overwrite_makes_no_api_call(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that a declined overwrite skips synthesis and leaves the existing file untouched."""
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    output_path = tmp_config.output_dir / "article.wav"
    output_path.write_bytes(b"original")
    monkeypatch.setattr(reader, "confirm_overwrite", lambda *_a, **_kw: False)

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=MagicMock(),
        options=reader.ReadOptions(),
    )

    assert result is False
    fake_tts_client.synthesize_speech.assert_not_called()
    assert output_path.read_bytes() == b"original"


def test_process_file_permission_error_is_printed_not_logged(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a PermissionError during synthesis is printed, not logger.exception'd."""
    fake_tts_client.synthesize_speech.side_effect = PermissionError("denied")
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    logger = MagicMock()

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=logger,
        options=reader.ReadOptions(),
    )

    assert result is False
    assert "Permission error while processing" in capsys.readouterr().out
    logger.exception.assert_not_called()


def test_process_file_oserror_is_printed_not_logged(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that an OSError during synthesis is printed, not logger.exception'd."""
    fake_tts_client.synthesize_speech.side_effect = OSError("disk full")
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    logger = MagicMock()

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=logger,
        options=reader.ReadOptions(),
    )

    assert result is False
    assert "OS error while processing" in capsys.readouterr().out
    logger.exception.assert_not_called()


def test_process_file_unexpected_error_is_logged_with_exception(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that an unanticipated exception is routed through logger.exception, once."""
    fake_tts_client.synthesize_speech.side_effect = ValueError("boom")
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    logger = MagicMock()

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=logger,
        options=reader.ReadOptions(),
    )

    assert result is False
    logger.exception.assert_called_once()
    assert str(tmp_config.error_log_path) in capsys.readouterr().out


def test_process_file_unreadable_input_is_a_per_file_error(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a read failure is caught inside process_file, not raised to the caller."""
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")

    def _raise(*_args: object, **_kwargs: object) -> str:
        raise PermissionError("locked")

    monkeypatch.setattr(type(filepath), "read_text", _raise)
    logger = MagicMock()

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=logger,
        options=reader.ReadOptions(),
    )

    assert result is False
    assert "Permission error while processing" in capsys.readouterr().out


def test_process_file_file_not_found_prints_distinct_message(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Test that FileNotFoundError gets its own message, not the generic OSError one.

    Pins the handler-ordering risk called out in the Phase 3a handoff: FileNotFoundError
    and PermissionError are both OSError subclasses, so reordering the except clauses
    would silently swallow this specific message into the generic OSError branch.
    """
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")

    def _raise(*_args: object, **_kwargs: object) -> str:
        raise FileNotFoundError("vanished")

    monkeypatch.setattr(type(filepath), "read_text", _raise)
    logger = MagicMock()

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=MagicMock(),
        logger=logger,
        options=reader.ReadOptions(),
    )

    assert result is False
    assert "File error while processing" in capsys.readouterr().out
    logger.exception.assert_not_called()


def test_process_file_empty_input_file_logs_zero_characters(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    isolated_logging: None,
) -> None:
    """Test the zero-character boundary: an empty input file still synthesizes and logs."""
    fake_tts_client.synthesize_speech.return_value = SimpleNamespace(
        audio_content=b"\x00\x01"
    )
    filepath = tmp_config.input_dir / "empty.txt"
    filepath.write_text("", encoding="utf-8")
    usage_logger = reader.initialize_usage_logger(tmp_config.usage_log_path)

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=tmp_config,
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_logger=usage_logger,
        logger=MagicMock(),
        options=reader.ReadOptions(),
    )

    assert result is True
    assert fake_tts_client.synthesize_speech.call_count == 1
    log_content = tmp_config.usage_log_path.read_text(encoding="utf-8")
    assert "characters: 0" in log_content


def test_process_file_random_voice_mode_selects_from_pool(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    isolated_logging: None,
) -> None:
    """
    Test that VoiceMode.RANDOM reaches select_voice and logs the drawn voice.

    Every other process_file/run_read test uses tmp_config's VoiceMode.FIXED, leaving the
    RANDOM branch of select_voice() untested at this layer. A single-element pool makes
    the draw deterministic without needing to control the RNG.
    """
    fake_tts_client.synthesize_speech.return_value = SimpleNamespace(
        audio_content=b"\x00\x01"
    )
    config = replace(tmp_config, voice_mode=VoiceMode.RANDOM)
    filepath = config.input_dir / "article.txt"
    filepath.write_text("Hello world.", encoding="utf-8")
    usage_logger = reader.initialize_usage_logger(config.usage_log_path)

    result = reader.process_file(
        filepath,
        client=fake_tts_client,
        config=config,
        voice_pool=("en-US-Chirp3-HD-Puck",),
        usage_logger=usage_logger,
        logger=MagicMock(),
        options=reader.ReadOptions(),
    )

    assert result is True
    log_content = config.usage_log_path.read_text(encoding="utf-8")
    assert "voice: en-US-Chirp3-HD-Puck" in log_content


# ---------------------------------------------------------------------------
# plan_dry_run / print_dry_run
# ---------------------------------------------------------------------------


def test_plan_dry_run_empty_file_has_one_chunk_zero_chars(
    tmp_config: StarlingConfig,
) -> None:
    """Test the zero-character boundary in plan_dry_run's measurement."""
    filepath = tmp_config.input_dir / "empty.txt"
    filepath.write_text("", encoding="utf-8")

    entries = reader.plan_dry_run([filepath], tmp_config)

    assert len(entries) == 1
    assert entries[0].char_count == 0
    assert entries[0].chunk_count == 1


def test_plan_dry_run_skips_unreadable_file_but_continues_batch(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that one unreadable file is skipped (printed, not raised) while the rest plan."""
    bad = tmp_config.input_dir / "bad.txt"
    bad.write_text("placeholder", encoding="utf-8")
    good = tmp_config.input_dir / "good.txt"
    good.write_text("Readable content.", encoding="utf-8")

    original_read_text = type(bad).read_text

    def _flaky_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "bad.txt":
            raise PermissionError("locked")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(type(bad), "read_text", _flaky_read_text)

    entries = reader.plan_dry_run([bad, good], tmp_config)

    assert [entry.path.name for entry in entries] == ["good.txt"]
    assert "File error while processing" in capsys.readouterr().out


def test_print_dry_run_empty_entries_reports_zero_totals(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test the zero-files boundary: an empty entries list still renders a valid report."""
    reader.print_dry_run([], tmp_config)

    out = capsys.readouterr().out
    assert "0 file(s), 0 characters would be billed." in out
    assert "*" not in out


def test_print_dry_run_overwrite_note_depends_on_assume_yes(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that the existing-output note's wording flips on assume_yes, not just its presence."""
    entry = reader.DryRunEntry(
        path=tmp_config.input_dir / "a.txt",
        output_path=tmp_config.output_dir / "a.wav",
        char_count=10,
        chunk_count=1,
        output_exists=True,
    )

    reader.print_dry_run([entry], tmp_config, assume_yes=False)
    declined_out = capsys.readouterr().out
    assert "already exists; `read` would prompt before overwriting." in declined_out

    reader.print_dry_run([entry], tmp_config, assume_yes=True)
    forced_out = capsys.readouterr().out
    assert "would be overwritten (--yes)." in forced_out


def test_print_dry_run_chunk_count_pluralization(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test the singular/plural boundary at chunk_count == 1 vs > 1."""
    single = reader.DryRunEntry(
        path=tmp_config.input_dir / "one.txt",
        output_path=tmp_config.output_dir / "one.wav",
        char_count=5,
        chunk_count=1,
        output_exists=False,
    )
    multi = reader.DryRunEntry(
        path=tmp_config.input_dir / "many.txt",
        output_path=tmp_config.output_dir / "many.wav",
        char_count=9000,
        chunk_count=2,
        output_exists=False,
    )

    reader.print_dry_run([single, multi], tmp_config)

    out = capsys.readouterr().out
    assert "1 chunk ->" in out
    assert "2 chunks ->" in out


# ---------------------------------------------------------------------------
# run_read
# ---------------------------------------------------------------------------


def test_run_read_empty_input_dir_needs_no_credentials(
    tmp_config: StarlingConfig,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that an empty input directory returns 0 without constructing a TTS client."""

    def _raise() -> None:
        raise AssertionError("TextToSpeechClient should not be constructed")

    monkeypatch.setattr(reader.texttospeech, "TextToSpeechClient", _raise)

    result = reader.run_read(config=tmp_config)

    assert result == 0
    assert capsys.readouterr().out.strip() == "No text files found."


def test_run_read_dry_run_makes_no_api_call(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that --dry-run reports both files and never constructs a TextToSpeechClient."""
    (tmp_config.input_dir / "a.txt").write_text("Hello world.", encoding="utf-8")
    (tmp_config.input_dir / "b.txt").write_text("Second file.", encoding="utf-8")

    def _raise() -> None:
        raise AssertionError("TextToSpeechClient should not be constructed")

    monkeypatch.setattr(reader.texttospeech, "TextToSpeechClient", _raise)

    result = reader.run_read(
        config=tmp_config, options=reader.ReadOptions(dry_run=True)
    )

    out = capsys.readouterr().out
    assert result == 0
    assert "a.txt" in out
    assert "b.txt" in out
    assert "no Google API calls" in out


def test_run_read_dry_run_does_not_archive_or_prompt(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that --dry-run never prompts and never moves input files into the archive."""
    filepath_a = tmp_config.input_dir / "a.txt"
    filepath_a.write_text("Hello world.", encoding="utf-8")
    filepath_b = tmp_config.input_dir / "b.txt"
    filepath_b.write_text("Second file.", encoding="utf-8")
    (tmp_config.output_dir / "a.wav").write_bytes(b"existing")

    def _raise(*_args: object, **_kwargs: object) -> bool:
        raise AssertionError("confirm_overwrite should not be called during --dry-run")

    monkeypatch.setattr(reader, "confirm_overwrite", _raise)

    result = reader.run_read(
        config=tmp_config, options=reader.ReadOptions(dry_run=True)
    )

    assert result == 0
    assert filepath_a.exists()
    assert filepath_b.exists()
    assert list(tmp_config.archive_dir.iterdir()) == []


def test_run_read_dry_run_char_count_matches_what_read_bills(
    tmp_config: StarlingConfig,
) -> None:
    """Test that the dry-run char count equals len(remove_citations(raw)), not len(raw)."""
    raw = "A claim (Smith, 2020) with a footnote[1]."
    filepath = tmp_config.input_dir / "article.txt"
    filepath.write_text(raw, encoding="utf-8")

    entries = reader.plan_dry_run([filepath], tmp_config)

    assert len(entries) == 1
    expected = len(reader.remove_citations(raw))
    assert entries[0].char_count == expected
    assert expected < len(raw)


def test_run_read_archives_only_successful_files(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    isolated_logging: None,
) -> None:
    """Test that only the file whose synthesis succeeded is moved to the archive."""
    (tmp_config.input_dir / "a.txt").write_text("First.", encoding="utf-8")
    (tmp_config.input_dir / "b.txt").write_text("Second.", encoding="utf-8")
    fake_tts_client.synthesize_speech.side_effect = [
        SimpleNamespace(audio_content=b"\x00\x01"),
        OSError("disk full"),
    ]
    monkeypatch.setattr(
        reader.texttospeech, "TextToSpeechClient", lambda: fake_tts_client
    )

    result = reader.run_read(
        config=tmp_config, options=reader.ReadOptions(assume_yes=True)
    )

    assert result == 0
    assert not (tmp_config.input_dir / "a.txt").exists()
    assert (tmp_config.archive_dir / "a.txt").exists()
    assert (tmp_config.input_dir / "b.txt").exists()


def test_run_read_input_dir_option_overrides_config(
    tmp_config: StarlingConfig,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that ReadOptions.input_dir overrides config.input_dir for the file scan."""
    other_dir = tmp_path / "other_input"
    other_dir.mkdir()
    (other_dir / "override.txt").write_text("Override file.", encoding="utf-8")
    (tmp_config.input_dir / "ignored.txt").write_text("Ignored file.", encoding="utf-8")

    result = reader.run_read(
        config=tmp_config,
        options=reader.ReadOptions(input_dir=other_dir, dry_run=True),
    )

    out = capsys.readouterr().out
    assert result == 0
    assert "override.txt" in out
    assert "ignored.txt" not in out


def test_run_read_config_error_returns_one(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a ConfigError from ensure_directories returns 1 and prints its message."""

    def _raise(_config: StarlingConfig) -> None:
        raise reader.ConfigError("boom")

    monkeypatch.setattr(reader, "ensure_directories", _raise)

    result = reader.run_read(config=tmp_config)

    assert result == 1
    assert capsys.readouterr().out.strip() == "Error: boom"


def test_run_read_unknown_voice_returns_one(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that an unresolvable configured voice returns 1 naming the unknown voice."""
    (tmp_config.input_dir / "article.txt").write_text("Hello.", encoding="utf-8")
    config = replace(
        tmp_config, voice_mode=VoiceMode.RANDOM, voice_pool=("en-US-Nope-Z",)
    )
    monkeypatch.setattr(
        reader.texttospeech, "TextToSpeechClient", lambda: fake_tts_client
    )

    result = reader.run_read(config=config)

    assert result == 1
    assert capsys.readouterr().out.startswith("Error: Unknown voice name:")


def test_run_read_unreachable_catalog_returns_one(
    tmp_config: StarlingConfig,
    fake_tts_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a catalog fetch failure returns 1 with a network-error message."""
    (tmp_config.input_dir / "article.txt").write_text("Hello.", encoding="utf-8")
    monkeypatch.setattr(
        reader.texttospeech, "TextToSpeechClient", lambda: fake_tts_client
    )
    monkeypatch.setattr(
        reader,
        "fetch_voices",
        MagicMock(side_effect=GoogleAPICallError("unreachable")),
    )

    result = reader.run_read(config=tmp_config)

    assert result == 1
    assert "could not reach Google Text-to-Speech" in capsys.readouterr().out


def test_run_read_dry_run_needs_no_credentials_even_when_unconfigured(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """
    Test that --dry-run succeeds with credentials_path=None, not just "happens to work".

    Every other dry-run test uses tmp_config, which carries a *valid* fake_credentials
    path -- so none of them actually prove the "no-input-files/dry-run needs no
    credentials" ordering guarantee the handoff calls out as unpinned. This test removes
    credentials entirely so a future reordering that moves require_credentials ahead of
    the dry-run check would fail here.
    """
    config = replace(tmp_config, credentials_path=None)
    (config.input_dir / "article.txt").write_text("Hello.", encoding="utf-8")

    def _raise() -> None:
        raise AssertionError("TextToSpeechClient should not be constructed")

    monkeypatch.setattr(reader.texttospeech, "TextToSpeechClient", _raise)

    result = reader.run_read(config=config, options=reader.ReadOptions(dry_run=True))

    out = capsys.readouterr().out
    assert result == 0
    assert "article.txt" in out
    assert "credentials" not in out.lower()


def test_run_read_missing_credentials_returns_one_for_a_real_run(
    tmp_config: StarlingConfig,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a non-dry-run with no configured credentials fails via require_credentials."""
    config = replace(tmp_config, credentials_path=None)
    (config.input_dir / "article.txt").write_text("Hello.", encoding="utf-8")

    def _raise() -> None:
        raise AssertionError("TextToSpeechClient should not be constructed")

    monkeypatch.setattr(reader.texttospeech, "TextToSpeechClient", _raise)

    result = reader.run_read(config=config)

    assert result == 1
    assert "No Google Cloud credentials configured." in capsys.readouterr().out


def test_run_read_processes_files_in_sorted_filename_order(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that input_dir.glob results are sorted, regardless of creation order."""
    (tmp_config.input_dir / "c.txt").write_text("C content.", encoding="utf-8")
    (tmp_config.input_dir / "a.txt").write_text("A content.", encoding="utf-8")
    (tmp_config.input_dir / "b.txt").write_text("B content.", encoding="utf-8")

    result = reader.run_read(
        config=tmp_config, options=reader.ReadOptions(dry_run=True)
    )

    out = capsys.readouterr().out
    assert result == 0
    positions = [out.index(name) for name in ("a.txt", "b.txt", "c.txt")]
    assert positions == sorted(positions)


def test_run_read_ignores_non_txt_files(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that input_dir.glob("*.txt") does not pick up other file extensions."""
    (tmp_config.input_dir / "a.txt").write_text("Text file.", encoding="utf-8")
    (tmp_config.input_dir / "notes.md").write_text("Markdown file.", encoding="utf-8")

    result = reader.run_read(
        config=tmp_config, options=reader.ReadOptions(dry_run=True)
    )

    out = capsys.readouterr().out
    assert result == 0
    assert "a.txt" in out
    assert "notes.md" not in out


# ---------------------------------------------------------------------------
# format_monthly_total / run_usage
# ---------------------------------------------------------------------------


def test_format_monthly_total_zero_and_nonzero() -> None:
    """Test the rendered line for a zero total and for a nonzero total's percentage rounding."""
    zero = reader.format_monthly_total({"current_month": "2026-09", "total_chars": 0})
    nonzero = reader.format_monthly_total(
        {"current_month": "2026-09", "total_chars": 850_000}
    )

    assert zero == "[2026-09] Total characters logged this month: 0 | 0%"
    assert nonzero == "[2026-09] Total characters logged this month: 850,000 | 85%"


def test_run_usage_prints_the_same_line_read_prints(
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that `usage` prints exactly what format_monthly_total(get_monthly_total(...)) does."""
    month = datetime.now(tz=UTC).strftime("%Y-%m")
    tmp_config.usage_log_path.write_text(
        f"{month}-01 | file.txt | voice: v1 | characters: 12,345 | monthly total: 12,345\n",
        encoding="utf-8",
    )

    result = reader.run_usage(config=tmp_config)

    expected = reader.format_monthly_total(
        reader.get_monthly_total(tmp_config.usage_log_path)
    )
    assert result == 0
    assert capsys.readouterr().out == expected + "\n"
