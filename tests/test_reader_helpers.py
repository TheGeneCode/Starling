"""
Behavioral tests for starling.reader's pure/testable helper functions.

test_package.py only checks that these helpers exist and are callable
(``test_reader_exposes_pure_helpers``); this module exercises their actual
behavior, including boundary conditions around byte-length chunking, WAV
framing, and log parsing.
"""

from __future__ import annotations

import io
import threading
import wave
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from genekit.logging import dedicated_file_logger

from starling import reader

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# remove_citations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "A claim (Smith, 2020) and another (Jones, 2019, p. 12).",
            "A claim  and another .",
            id="traditional_and_page_number_citations",
        ),
        pytest.param(
            "(Smith & Jones, 2020a) test",
            " test",
            id="letter_suffixed_year",
        ),
        pytest.param(
            "Footnote here[1] and [22] more.",
            "Footnote here and  more.",
            id="footnote_markers",
        ),
        pytest.param(
            "(see figure 1) shows results.",
            "(see figure 1) shows results.",
            id="non_citation_parens_preserved",
        ),
        pytest.param(
            "(2020) alone.",
            "(2020) alone.",
            id="year_only_parens_not_removed",
        ),
        pytest.param("", "", id="empty_string"),
        pytest.param(
            "No citations here at all.", "No citations here at all.", id="no_match_noop"
        ),
    ],
)
def test_remove_citations(text: str, expected: str) -> None:
    """Test remove_citations against traditional citations, footnotes, and near-misses."""
    assert reader.remove_citations(text) == expected


# ---------------------------------------------------------------------------
# split_text_into_chunks
# ---------------------------------------------------------------------------


def test_split_text_into_chunks_single_short_sentence_stays_one_chunk() -> None:
    """Test that text under the byte budget produces a single chunk."""
    assert reader.split_text_into_chunks("Short sentence.") == ["Short sentence."]


def test_split_text_into_chunks_empty_string_returns_single_empty_chunk() -> None:
    """
    Pin the current (surprising) behavior for empty input.

    ``re.split`` on an empty string yields ``['']``, and the trailing-chunk
    flush appends ``"".strip()`` unconditionally, so the function returns
    ``['']`` rather than ``[]``. A caller that naively iterates chunks and
    calls the TTS API per chunk would send one empty-string request.
    """
    assert reader.split_text_into_chunks("") == [""]


def test_split_text_into_chunks_splits_at_sentence_boundaries() -> None:
    """Test that chunks are grouped by whole sentences up to the byte budget."""
    result = reader.split_text_into_chunks("One. Two. Three. Four.", max_bytes=10)
    assert result == ["One. Two.", "Three.", "Four."]
    for chunk in result:
        assert len(chunk.encode("utf-8")) <= 10


def test_split_text_into_chunks_oversized_single_sentence_exceeds_max_bytes() -> None:
    """
    Document a boundary defect: a lone sentence larger than max_bytes is never split.

    The function only ever appends a *complete* sentence to ``current_chunk``
    and never checks that append against ``max_bytes`` before accepting it as
    the new current chunk when the existing chunk was empty. A single run-on
    sentence therefore produces a chunk far in excess of the configured byte
    budget instead of being sub-split.
    """
    oversized_sentence = "A" * 5000 + "."
    result = reader.split_text_into_chunks(oversized_sentence, max_bytes=100)
    assert len(result) == 1
    assert len(result[0].encode("utf-8")) == 5001
    assert len(result[0].encode("utf-8")) > 100


def test_split_text_into_chunks_unicode_byte_length_not_char_length() -> None:
    """
    Test that the byte budget is enforced on UTF-8 bytes, not code points.

    A 251-character string of multi-byte "café " repeats encodes to 301
    bytes, so a char-length-based implementation would wrongly consider it
    within a 100-byte budget while the byte-based one (correctly) does not
    split it, since it's a single "sentence" — same oversized-sentence
    limitation as above, surfaced through unicode.
    """
    text = ("café " * 50) + "."
    result = reader.split_text_into_chunks(text, max_bytes=100)
    assert len(result) == 1
    assert len(result[0].encode("utf-8")) == 301


def test_split_text_into_chunks_default_max_bytes() -> None:
    """Test the default max_bytes=4500 boundary is honored when not overridden."""
    result = reader.split_text_into_chunks("Short sentence.")
    assert len(result[0].encode("utf-8")) <= 4500


# ---------------------------------------------------------------------------
# combine_audio_chunks
# ---------------------------------------------------------------------------


def test_combine_audio_chunks_empty_list_produces_valid_zero_frame_wav() -> None:
    """Test that an empty chunk list still produces a structurally valid WAV file."""
    wav_bytes = reader.combine_audio_chunks([], sample_rate=16000)
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 0


def test_combine_audio_chunks_concatenates_in_order() -> None:
    """Test that multiple chunks are concatenated in the given order, not reordered."""
    chunk_a = b"\x01\x00\x02\x00"
    chunk_b = b"\x03\x00\x04\x00"
    wav_bytes = reader.combine_audio_chunks([chunk_a, chunk_b])
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnframes() == 4
        assert wav_file.readframes(4) == chunk_a + chunk_b


def test_combine_audio_chunks_default_sample_rate() -> None:
    """Test that the default sample rate (24000 Hz) is applied when not overridden."""
    wav_bytes = reader.combine_audio_chunks([b"\x00\x00"])
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getframerate() == 24000


def test_combine_audio_chunks_single_chunk() -> None:
    """Test the boundary of exactly one chunk (not zero, not many)."""
    chunk = b"\x05\x00\x06\x00\x07\x00"
    wav_bytes = reader.combine_audio_chunks([chunk])
    with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
        assert wav_file.getnframes() == 3
        assert wav_file.readframes(3) == chunk


# ---------------------------------------------------------------------------
# get_monthly_total
# ---------------------------------------------------------------------------


def _current_month() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m")


def test_get_monthly_total_missing_file_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that a nonexistent usage log yields a zeroed-out result, not an error."""
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", tmp_path / "does_not_exist.log")
    result = reader.get_monthly_total()
    assert result == {
        "total_chars": 0,
        "current_month": _current_month(),
        "entries": [],
    }


def test_get_monthly_total_empty_file_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that a zero-length usage log yields a zeroed-out result."""
    log_path = tmp_path / "usage.log"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    result = reader.get_monthly_total()
    assert result["total_chars"] == 0
    assert result["entries"] == []


def test_get_monthly_total_ignores_other_months(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that lines from a different month are excluded from entries and total."""
    log_path = tmp_path / "usage.log"
    log_path.write_text(
        "1999-01-01 | old.txt | voice: v1 | characters: 500 | monthly total: 500\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    result = reader.get_monthly_total()
    assert result["total_chars"] == 0
    assert result["entries"] == []


def test_get_monthly_total_takes_last_matching_running_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that total_chars reflects the last current-month line's running total."""
    month = _current_month()
    log_path = tmp_path / "usage.log"
    log_path.write_text(
        f"{month}-01 | file1.txt | voice: v1 | characters: 1,000 | monthly total: 1,000\n"
        f"{month}-02 | file2.txt | voice: v2 | characters: 2,000 | monthly total: 3,000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    result = reader.get_monthly_total()
    assert result["total_chars"] == 3000
    assert len(result["entries"]) == 2


def test_get_monthly_total_malformed_total_field_is_suppressed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that a non-numeric 'monthly total' field is swallowed, not raised."""
    month = _current_month()
    log_path = tmp_path / "usage.log"
    log_path.write_text(
        f"{month}-01 | bad.txt | voice: v1 | characters: 1,000 | monthly total: not-a-number\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    result = reader.get_monthly_total()
    assert result["total_chars"] == 0
    assert len(result["entries"]) == 1


# ---------------------------------------------------------------------------
# log_usage
# ---------------------------------------------------------------------------


def test_log_usage_first_entry_running_total_equals_char_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_logging: None
) -> None:
    """Test that the running total on the first-ever log entry equals char_count."""
    log_path = tmp_path / "usage.log"
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    logger = dedicated_file_logger(
        "starling_test_log_usage_first",
        log_path,
        fmt="%(message)s",
    )

    reader.log_usage(logger, "file1.txt", "voice-a", 1234)

    content = log_path.read_text(encoding="utf-8")
    assert (
        "file1.txt | voice: voice-a | characters: 1,234 | monthly total: 1,234"
        in content
    )


def test_log_usage_accumulates_onto_existing_monthly_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_logging: None
) -> None:
    """Test that running total adds char_count on top of the prior monthly total."""
    month = _current_month()
    log_path = tmp_path / "usage.log"
    log_path.write_text(
        f"{month}-01 | file1.txt | voice: v1 | characters: 1,000 | monthly total: 1,000\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)
    logger = dedicated_file_logger(
        "starling_test_log_usage_accumulate",
        log_path,
        fmt="%(message)s",
    )

    reader.log_usage(logger, "file2.txt", "voice-b", 500)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert lines[-1].endswith(
        "file2.txt | voice: voice-b | characters: 500 | monthly total: 1,500"
    )


# ---------------------------------------------------------------------------
# initialize_usage_logger
# ---------------------------------------------------------------------------


def test_initialize_usage_logger_writes_to_usage_log_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_logging: None
) -> None:
    """Test that initialize_usage_logger's logger writes to USAGE_LOG_PATH."""
    log_path = tmp_path / "tts_usage.log"
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", log_path)

    usage_logger = reader.initialize_usage_logger()
    usage_logger.info("probe message")
    for handler in usage_logger.handlers:
        handler.flush()

    assert log_path.exists()
    assert "probe message" in log_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# spinner
# ---------------------------------------------------------------------------


def test_spinner_stops_promptly_when_event_is_cleared() -> None:
    """Test that spinner's thread terminates once the Event is cleared (no hang)."""
    should_spin = threading.Event()
    should_spin.set()
    thread = threading.Thread(target=reader.spinner, args=(should_spin,))
    thread.start()
    should_spin.clear()
    thread.join(timeout=2)
    assert not thread.is_alive()


def test_spinner_never_starts_when_event_not_set() -> None:
    """Test the boundary where the Event is already clear before the thread runs."""
    should_spin = threading.Event()
    thread = threading.Thread(target=reader.spinner, args=(should_spin,))
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
