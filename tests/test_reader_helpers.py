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
from typing import TYPE_CHECKING, Any

import pytest
from genekit.logging import dedicated_file_logger
from num2words import num2words

import starling.reader
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
# convert_numbers_to_words
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "$1,300 million", "1.3 billion dollars", id="million_rescaled_to_billion"
        ),
        pytest.param(
            "$1,300 MILLION",
            "1.3 billion dollars",
            id="unit_matching_is_case_insensitive",
        ),
        pytest.param(
            "$1 million",
            "1 million dollars",
            id="boundary_exactly_one_million_no_comma",
        ),
        pytest.param(
            "$1,234.56",
            "one thousand two hundred and thirty-four dollars fifty-six cents",
            id="currency_with_cents",
        ),
        pytest.param(
            "$1,000,000", "one million dollars", id="plain_currency_with_commas"
        ),
        pytest.param(
            "1,234",
            "one thousand two hundred and thirty-four",
            id="plain_number_with_comma_no_dollar_sign",
        ),
        pytest.param("42", "42", id="number_without_comma_is_untouched"),
        pytest.param("$0.99", "$0.99", id="currency_without_comma_group_is_untouched"),
        pytest.param(
            "-1,234",
            "-one thousand two hundred and thirty-four",
            id="minus_sign_preserved_outside_the_match",
        ),
    ],
)
def test_convert_numbers_to_words(text: str, expected: str) -> None:
    """Test convert_numbers_to_words across currency scaling, plain numbers, and no-ops."""
    assert reader.convert_numbers_to_words(text) == expected


def test_convert_numbers_to_words_decimal_value_stays_in_million_branch() -> None:
    """Test a non-integer scaled value that stays under 1e9 (nominal million branch)."""
    result = reader.convert_numbers_to_words("$2.5 million")
    assert result == "2.5 million dollars"


def test_convert_numbers_to_words_million_scaled_just_under_billion_threshold() -> None:
    """Test a large-but-still-billion-range scaled value, just below the trillion defect."""
    result = reader.convert_numbers_to_words("$500,000 million")
    assert result == "500 billion dollars"


def test_convert_numbers_to_words_sub_one_million_value_loses_unit_label() -> None:
    """
    Document a second boundary defect: a "million" value scaled below 1e6 drops its unit.

    ``scale_currency``'s final ``else`` branch (comment: "Should be rare for million+
    inputs") sets ``new_unit = ""`` when the scaled total is under 1e6. That branch is
    reachable whenever the numeric value in front of "million" is itself less than 1
    (e.g. "$0.5 million" scales to 500,000, which is under 1e6). The result drops the
    unit word entirely and leaves a double space where it used to sit, since
    ``f"{val_fmt} {new_unit} dollars".strip()`` only trims the ends, not the interior.
    """
    result = reader.convert_numbers_to_words("$0.5 million")
    assert result == "500000  dollars"


def test_convert_numbers_to_words_beyond_billion_mislabels_as_billion() -> None:
    """
    Document a boundary defect: scaled values >= 1e12 are still labeled 'billion'.

    ``scale_currency`` only ever re-labels the output as 'million' or
    'billion' — there's no branch for 'trillion' even though 'trillion' is
    an accepted *input* unit and a large-enough 'million'/'billion' input
    can scale past 1e12. "$1,300,000 million" is 1.3 trillion, but the
    function emits "1300 billion dollars" instead of "1.3 trillion dollars".
    """
    result = reader.convert_numbers_to_words("$1,300,000 million")
    assert result == "1300 billion dollars"


def test_convert_numbers_to_words_malformed_value_falls_back_to_original() -> None:
    """Test that text with no comma-grouped numbers passes through unmodified."""
    text = "The year 2020 had 42 events."
    assert reader.convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_bare_dollar_sign_with_no_digits() -> None:
    """Test that a bare '$' with no digit group is left untouched by every regex branch."""
    text = "Costs $ and more $ signs."
    assert reader.convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_text_with_no_numbers_at_all() -> None:
    """Test that text with no numerals passes through unchanged."""
    text = "No numerals here whatsoever."
    assert reader.convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_decimal_currency_with_commas() -> None:
    """Test decimal currency against num2words directly, not a hard-coded locale string."""
    expected = num2words(1234.56, to="currency", currency="USD")
    expected = expected.removesuffix(", zero cents").replace(",", "")
    assert reader.convert_numbers_to_words("$1,234.56") == expected


def test_currency_to_words_falls_back_when_num2words_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that currency_to_words returns the original match when num2words raises."""

    def raiser(*args: Any, **kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(starling.reader, "num2words", raiser)
    assert reader.convert_numbers_to_words("$1,000") == "$1,000"


def test_number_to_words_falls_back_when_num2words_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that number_to_words returns the original match when num2words raises."""

    def raiser(*args: Any, **kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(starling.reader, "num2words", raiser)
    assert reader.convert_numbers_to_words("1,000 people") == "1,000 people"


def test_convert_numbers_to_words_astronomical_scale_mislabels_as_infinity() -> None:
    r"""
    Document a third boundary defect: a value so large the scaling overflows to inf.

    ``scale_currency`` has no upper guard on the digit group matched by ``\d+``
    (unbounded repetition), so a large-enough literal times a ``multipliers[unit]``
    float produces ``float("inf")``. ``float("inf").is_integer()`` is ``False`` (it
    doesn't raise), so execution falls into the same formatting path as any other
    non-integer scaled value and silently emits the literal word "inf" instead of
    raising or reporting an out-of-range condition.
    """
    result = reader.convert_numbers_to_words("$" + "9" * 320 + " trillion")
    assert result == "inf billion dollars"


def test_convert_numbers_to_words_unicode_digits_are_converted_without_raising() -> None:
    r"""
    Test that non-ASCII Unicode decimal digits (regex ``\d``) do not crash conversion.

    Python's ``\\d`` matches every Unicode ``Nd``-category digit, not just ASCII
    0-9, and both ``int()`` and ``float()`` parse them. A plain-number match built
    entirely from Arabic-Indic digits must still convert cleanly instead of hitting
    an unhandled exception in ``number_to_words``.
    """
    result = reader.convert_numbers_to_words("٢٣٤,٥٦٧")
    assert result == "two hundred and thirty-four thousand five hundred and sixty-seven"


def test_convert_numbers_to_words_then_chunking_crosses_byte_boundary_after_expansion() -> None:
    """
    Test the byte-vs-character combination boundary the handoff calls out.

    Two short sentences whose *raw* digit form fits in a single 60-byte chunk
    expand, once spelled out as words, to a byte length that no longer fits —
    ``split_text_into_chunks`` must see 2 chunks for the converted text even
    though the untouched raw text would only ever need 1. This pins the
    invariant that chunk counting always runs on the post-conversion text
    (matching how ``plan_dry_run`` and ``process_file`` compose the two calls),
    not on the original digits.
    """
    raw = "There are 1,234 reasons. There are 5,678 more reasons."
    converted = reader.convert_numbers_to_words(reader.remove_citations(raw))

    raw_chunks = reader.split_text_into_chunks(raw, max_bytes=60)
    converted_chunks = reader.split_text_into_chunks(converted, max_bytes=60)

    assert len(raw_chunks) == 1
    assert len(converted_chunks) == 2


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


def test_get_monthly_total_explicit_path_overrides_module_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Test that an explicit usage_log_path argument is read instead of USAGE_LOG_PATH.

    The module attribute is pointed at a log claiming a large running total; the
    explicit argument points at a different (empty) log. If the explicit
    argument were ignored, this would incorrectly report the module-default log's
    total instead of zero.
    """
    month = _current_month()
    module_default_path = tmp_path / "module_default.log"
    module_default_path.write_text(
        f"{month}-01 | old.txt | voice: v1 | characters: 9,999 | monthly total: 9,999\n",
        encoding="utf-8",
    )
    explicit_path = tmp_path / "explicit.log"
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", module_default_path)

    result = reader.get_monthly_total(usage_log_path=explicit_path)

    assert result["total_chars"] == 0
    assert result["entries"] == []


def test_get_monthly_total_resolves_module_attr_at_call_time_not_import_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Test that USAGE_LOG_PATH is read fresh on every call, not frozen at import.

    This is the specific regression the Phase 2a handoff calls out: resolving the
    default *inside* the function body (rather than as
    ``usage_log_path: Path = USAGE_LOG_PATH`` in the signature) means two calls in
    the same process, with the module attribute changed in between, must each see
    the value current at call time.
    """
    month = _current_month()
    first_log = tmp_path / "first.log"
    first_log.write_text(
        f"{month}-01 | a.txt | voice: v1 | characters: 100 | monthly total: 100\n",
        encoding="utf-8",
    )
    second_log = tmp_path / "second.log"
    second_log.write_text(
        f"{month}-01 | b.txt | voice: v1 | characters: 200 | monthly total: 200\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(reader, "USAGE_LOG_PATH", first_log)
    first_result = reader.get_monthly_total()

    monkeypatch.setattr(reader, "USAGE_LOG_PATH", second_log)
    second_result = reader.get_monthly_total()

    assert first_result["total_chars"] == 100
    assert second_result["total_chars"] == 200


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


def test_initialize_usage_logger_explicit_path_overrides_module_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_logging: None
) -> None:
    """
    Test that an explicit usage_log_path argument wins over USAGE_LOG_PATH.

    Phase 2a resolves the parameter default *inside* the function body
    (``path = usage_log_path if usage_log_path is not None else USAGE_LOG_PATH``)
    rather than as a frozen default argument, specifically so this call-site
    override still works. Point the module attribute at one file and pass a
    different path explicitly; only the explicit path should receive the write.
    """
    module_default_path = tmp_path / "module_default.log"
    explicit_path = tmp_path / "explicit_override.log"
    monkeypatch.setattr(reader, "USAGE_LOG_PATH", module_default_path)

    usage_logger = reader.initialize_usage_logger(usage_log_path=explicit_path)
    usage_logger.info("goes to explicit path")
    for handler in usage_logger.handlers:
        handler.flush()

    assert explicit_path.exists()
    assert "goes to explicit path" in explicit_path.read_text(encoding="utf-8")
    assert not module_default_path.exists()


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


# ---------------------------------------------------------------------------
# confirm_synthesis
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("y", id="lowercase_y"),
        pytest.param("Y", id="uppercase_y"),
    ],
)
def test_confirm_synthesis_accepts_y_any_case(answer: str) -> None:
    """Test that confirm_synthesis returns True for exactly 'y' or 'Y'."""
    assert reader.confirm_synthesis(prompt=lambda _: answer) is True


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("", id="empty_string"),
        pytest.param("n", id="lowercase_n"),
        pytest.param("no", id="no"),
        pytest.param("yes", id="yes_not_y"),
        pytest.param(" y", id="y_with_leading_space"),
        pytest.param("y ", id="y_with_trailing_space"),
    ],
)
def test_confirm_synthesis_rejects_empty_and_other(answer: str) -> None:
    """Test that confirm_synthesis returns False for anything other than exact 'y' or 'Y'."""
    assert reader.confirm_synthesis(prompt=lambda _: answer) is False


def test_confirm_synthesis_prompt_text_is_stable() -> None:
    """Test that the prompt text sent to the user matches the documented wording exactly."""
    captured: list[str] = []

    def _capture(message: str) -> str:
        captured.append(message)
        return "y"

    reader.confirm_synthesis(prompt=_capture)

    assert captured == ["Proceed with synthesis? (y/n): "]


def test_confirm_synthesis_propagates_prompt_exception() -> None:
    """
    Test that an exception from the prompt callable (e.g. EOFError from closed stdin) propagates.

    confirm_synthesis does not wrap the prompt call in a try/except, so a prompt source
    that cannot read (a closed stdin, piped-empty input under `-y`-less automation) must
    raise straight through rather than being silently treated as a decline.
    """

    def _raise(_message: str) -> str:
        raise EOFError

    with pytest.raises(EOFError):
        reader.confirm_synthesis(prompt=_raise)
