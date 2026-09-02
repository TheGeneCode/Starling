"""Behavioral tests for capture.py's pure text-processing helpers."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest
from num2words import num2words

import starling.capture
from starling.capture import (
    console_executable,
    convert_numbers_to_words,
    make_filename_ready,
    refine_text,
    run_article_reader,
    shorten_text,
)

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# make_filename_ready
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            "abc DEF 123-_.() ", "abc DEF 123-_.() ", id="already_valid_unchanged"
        ),
        pytest.param(
            'a:b?c"d<e>f|g*h/i\\j', "abcdefghij", id="strips_windows_reserved_chars"
        ),
        pytest.param("", "", id="empty_string"),
        pytest.param(":::???", "", id="all_invalid_chars_returns_empty"),
        pytest.param("café_文件", "caf_", id="strips_unicode_accents_and_cjk"),
    ],
)
def test_make_filename_ready(text: str, expected: str) -> None:
    """Test make_filename_ready across valid, invalid, empty, and unicode input."""
    assert make_filename_ready(text) == expected


# ---------------------------------------------------------------------------
# shorten_text
# ---------------------------------------------------------------------------


def test_shorten_text_at_exactly_max_length_is_unchanged() -> None:
    """Test the boundary where len(text) == max_length: no truncation."""
    text = "x" * 92
    assert shorten_text(text) == text


def test_shorten_text_one_over_max_length_truncates_with_ellipsis() -> None:
    """Test the boundary just above max_length: truncates to max_length total chars."""
    text = "x" * 93
    result = shorten_text(text)
    assert len(result) == 92
    assert result == "x" * 89 + "..."


def test_shorten_text_empty_string() -> None:
    """Test that an empty string is returned unchanged."""
    assert shorten_text("") == ""


def test_shorten_text_custom_max_length() -> None:
    """Test shorten_text honors a caller-supplied max_length parameter."""
    result = shorten_text("abcdefghij", max_length=5)
    assert result == "ab..."
    assert len(result) == 5


def test_shorten_text_max_length_three_is_ellipsis_only() -> None:
    """Test the smallest max_length for which the ellipsis-only output is still correct."""
    result = shorten_text("abcdefghij", max_length=3)
    assert result == "..."
    assert len(result) == 3


def test_shorten_text_max_length_below_three_produces_output_longer_than_max_length() -> (
    None
):
    """
    Document a boundary defect: max_length < 3 makes the result LONGER than max_length.

    ``text[: max_length - 3]`` goes negative once ``max_length < 3``, so instead of
    truncating harder it slices from the *end* of the string (e.g. ``max_length=2``
    gives ``text[:-1]``, i.e. "all but the last character"). The three-character
    "..." is then appended on top, so the returned string is far longer than the
    caller's requested max_length instead of being capped by it.
    """
    text = "abcdef"
    result = shorten_text(text, max_length=2)
    assert result == "abcde..."
    assert len(result) > 2


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
    assert convert_numbers_to_words(text) == expected


def test_convert_numbers_to_words_decimal_value_stays_in_million_branch() -> None:
    """Test a non-integer scaled value that stays under 1e9 (nominal million branch)."""
    result = convert_numbers_to_words("$2.5 million")
    assert result == "2.5 million dollars"


def test_convert_numbers_to_words_million_scaled_just_under_billion_threshold() -> None:
    """Test a large-but-still-billion-range scaled value, just below the trillion defect."""
    result = convert_numbers_to_words("$500,000 million")
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
    result = convert_numbers_to_words("$0.5 million")
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
    result = convert_numbers_to_words("$1,300,000 million")
    assert result == "1300 billion dollars"


def test_convert_numbers_to_words_malformed_value_falls_back_to_original() -> None:
    """Test that text with no comma-grouped numbers passes through unmodified."""
    text = "The year 2020 had 42 events."
    assert convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_bare_dollar_sign_with_no_digits() -> None:
    """Test that a bare '$' with no digit group is left untouched by every regex branch."""
    text = "Costs $ and more $ signs."
    assert convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_text_with_no_numbers_at_all() -> None:
    """Test that text with no numerals passes through unchanged."""
    text = "No numerals here whatsoever."
    assert convert_numbers_to_words(text) == text


def test_convert_numbers_to_words_decimal_currency_with_commas() -> None:
    """Test decimal currency against num2words directly, not a hard-coded locale string."""
    expected = num2words(1234.56, to="currency", currency="USD")
    expected = expected.removesuffix(", zero cents").replace(",", "")
    assert convert_numbers_to_words("$1,234.56") == expected


def test_currency_to_words_falls_back_when_num2words_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that currency_to_words returns the original match when num2words raises."""

    def raiser(*args: Any, **kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(starling.capture, "num2words", raiser)
    assert convert_numbers_to_words("$1,000") == "$1,000"


def test_number_to_words_falls_back_when_num2words_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that number_to_words returns the original match when num2words raises."""

    def raiser(*args: Any, **kwargs: Any) -> None:
        raise ValueError("boom")

    monkeypatch.setattr(starling.capture, "num2words", raiser)
    assert convert_numbers_to_words("1,000 people") == "1,000 people"


# ---------------------------------------------------------------------------
# refine_text
# ---------------------------------------------------------------------------


def test_refine_text_removes_footnote_markers() -> None:
    """Test that bracketed footnote markers are stripped."""
    result = refine_text("Hello [1] world [22].")
    assert result == "Hello  world ."


def test_refine_text_truncates_at_related_marker() -> None:
    """Test that text is cut off at the first 'Related:' occurrence."""
    result = refine_text("Keep this. Related: some other stuff here")
    assert result == "Keep this. "


def test_refine_text_stops_at_exact_discard_line() -> None:
    """Test that a line matching a discard marker exactly drops itself and all following lines."""
    result = refine_text("Line one\nFor more\nLine three\n")
    assert result == "Line one\n"


def test_refine_text_partial_match_discard_line_is_not_truncated() -> None:
    """
    Document a boundary footgun: discard-line matching requires an EXACT full-line match.

    ``line.strip() in discard_after_lines`` only matches when the entire
    stripped line equals "For more" or "THE LATEST NEWS" verbatim — a line
    like "For more info" (a very plausible real-world variant) does not
    trigger the cutoff at all, so trailing boilerplate leaks straight
    through into the narrated text.
    """
    text = "Line one\nFor more info\nLine three\n"
    assert refine_text(text) == text


def test_refine_text_stops_at_latest_news_marker_line() -> None:
    """Test the second discard-line marker, 'THE LATEST NEWS', behaves like 'For more'."""
    result = refine_text("Line one\nTHE LATEST NEWS\nLine three\n")
    assert result == "Line one\n"


def test_refine_text_converts_embedded_numbers() -> None:
    """Test that refine_text applies convert_numbers_to_words to the surviving text."""
    result = refine_text("There are $1,300 million reasons.")
    assert result == "There are 1.3 billion dollars reasons."


def test_refine_text_no_discard_markers_present() -> None:
    """Test that text without any discard marker or footnote passes through unchanged."""
    text = "Plain text with nothing special.\nSecond line.\n"
    assert refine_text(text) == text


# ---------------------------------------------------------------------------
# console_executable
# ---------------------------------------------------------------------------


def test_console_executable_swaps_pythonw_for_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that a sibling python.exe is swapped in for pythonw.exe on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    (tmp_path / "python.exe").touch()

    assert console_executable() == str(tmp_path / "python.exe")


def test_console_executable_keeps_pythonw_when_no_sibling_python(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that pythonw.exe is returned unchanged when no sibling python.exe exists."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))

    assert console_executable() == str(tmp_path / "pythonw.exe")


def test_console_executable_is_identity_off_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that non-Windows platforms never attempt the pythonw.exe swap."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(sys, "executable", "/usr/bin/pythonw.exe")

    assert console_executable() == "/usr/bin/pythonw.exe"


def test_console_executable_matches_pythonw_name_case_insensitively(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that a mixed-case 'PythonW.EXE' basename still triggers the swap."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "PythonW.EXE"))
    (tmp_path / "python.exe").touch()

    assert console_executable() == str(tmp_path / "python.exe")


def test_console_executable_no_swap_when_already_console_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Test that an already-console interpreter (not pythonw.exe) is returned unchanged."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))

    assert console_executable() == str(tmp_path / "python.exe")


def test_console_executable_accepts_a_directory_named_like_the_sibling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """
    Document a boundary defect: the sibling check uses exists(), not is_file().

    If a *directory* happens to be named "python.exe" next to pythonw.exe, ``Path.exists()``
    returns True for it just as it would for a real file, so ``console_executable`` swaps in
    a path that is not actually executable instead of falling back to pythonw.exe. Launching
    ``subprocess.Popen`` against that path would fail confusingly later, rather than at this
    well-defined check.
    """
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    (tmp_path / "python.exe").mkdir()

    assert console_executable() == str(tmp_path / "python.exe")


# ---------------------------------------------------------------------------
# run_article_reader
# ---------------------------------------------------------------------------
#
# capture.py launches `[console_executable(), "-m", "starling", "read"]` with
# CREATE_NEW_CONSOLE gated behind sys.platform == "win32" (that constant doesn't
# exist off Windows, so passing it unconditionally would crash on Linux/macOS).
# These tests monkeypatch sys.platform, so console_executable() sees "win32" on
# the Windows-branch test below; the assertion stays sys.executable because the
# test interpreter is not named pythonw.exe.


@pytest.mark.skipif(
    sys.platform != "win32",
    reason=(
        "subprocess.CREATE_NEW_CONSOLE is bound by the real subprocess module only "
        "on an actual Windows interpreter; monkeypatching sys.platform can't create "
        "it, so this branch is only genuinely exercisable on a real win32 runner."
    ),
)
def test_run_article_reader_windows_uses_new_console_flag_and_module_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the win32 branch: CREATE_NEW_CONSOLE flag and exact argv."""
    monkeypatch.setattr(sys, "platform", "win32")
    captured: dict[str, Any] = {}

    def fake_popen(argv: list[str], **kwargs: Any) -> None:
        captured["argv"] = argv
        captured["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_article_reader()

    assert captured["argv"] == [sys.executable, "-m", "starling", "read"]
    assert captured["kwargs"] == {
        "creationflags": subprocess.CREATE_NEW_CONSOLE,
    }


def test_run_article_reader_non_windows_uses_zero_creationflags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Test the non-Windows branch: creationflags=0, no reference to the Windows-only constant.

    Boundary: `subprocess.CREATE_NEW_CONSOLE` genuinely does not exist on
    Linux/macOS, so evaluating that attribute unconditionally would raise
    AttributeError on those platforms -- this pins that the ternary short-
    circuits before ever touching it.
    """
    monkeypatch.setattr(sys, "platform", "linux")
    captured: dict[str, Any] = {}

    def fake_popen(argv: list[str], **kwargs: Any) -> None:
        captured["argv"] = argv
        captured["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    run_article_reader()

    assert captured["argv"] == [sys.executable, "-m", "starling", "read"]
    assert captured["kwargs"] == {"creationflags": 0}
