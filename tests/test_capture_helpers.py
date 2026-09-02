"""
Behavioral tests for capture.py's pure text-processing helpers.

capture.py cannot be imported directly (it builds a Tkinter GUI and calls
``root.mainloop()`` at module scope — see ``test_capture_module_parses_without_importing``
in ``test_package.py``, which only verifies the functions exist via ``ast``).
The ``capture_helpers`` fixture (tests/conftest.py) execs just the pure
helper functions into an isolated namespace so their actual behavior can be
exercised here without ever constructing a GUI window.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

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
def test_make_filename_ready(
    capture_helpers: dict[str, Any], text: str, expected: str
) -> None:
    """Test make_filename_ready across valid, invalid, empty, and unicode input."""
    assert capture_helpers["make_filename_ready"](text) == expected


# ---------------------------------------------------------------------------
# shorten_text
# ---------------------------------------------------------------------------


def test_shorten_text_at_exactly_max_length_is_unchanged(
    capture_helpers: dict[str, Any],
) -> None:
    """Test the boundary where len(text) == max_length: no truncation."""
    text = "x" * 92
    assert capture_helpers["shorten_text"](text) == text


def test_shorten_text_one_over_max_length_truncates_with_ellipsis(
    capture_helpers: dict[str, Any],
) -> None:
    """Test the boundary just above max_length: truncates to max_length total chars."""
    text = "x" * 93
    result = capture_helpers["shorten_text"](text)
    assert len(result) == 92
    assert result == "x" * 89 + "..."


def test_shorten_text_empty_string(capture_helpers: dict[str, Any]) -> None:
    """Test that an empty string is returned unchanged."""
    assert capture_helpers["shorten_text"]("") == ""


def test_shorten_text_custom_max_length(capture_helpers: dict[str, Any]) -> None:
    """Test shorten_text honors a caller-supplied max_length parameter."""
    result = capture_helpers["shorten_text"]("abcdefghij", max_length=5)
    assert result == "ab..."
    assert len(result) == 5


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
def test_convert_numbers_to_words(
    capture_helpers: dict[str, Any], text: str, expected: str
) -> None:
    """Test convert_numbers_to_words across currency scaling, plain numbers, and no-ops."""
    assert capture_helpers["convert_numbers_to_words"](text) == expected


def test_convert_numbers_to_words_beyond_billion_mislabels_as_billion(
    capture_helpers: dict[str, Any],
) -> None:
    """
    Document a boundary defect: scaled values >= 1e12 are still labeled 'billion'.

    ``scale_currency`` only ever re-labels the output as 'million' or
    'billion' — there's no branch for 'trillion' even though 'trillion' is
    an accepted *input* unit and a large-enough 'million'/'billion' input
    can scale past 1e12. "$1,300,000 million" is 1.3 trillion, but the
    function emits "1300 billion dollars" instead of "1.3 trillion dollars".
    """
    result = capture_helpers["convert_numbers_to_words"]("$1,300,000 million")
    assert result == "1300 billion dollars"


def test_convert_numbers_to_words_malformed_value_falls_back_to_original(
    capture_helpers: dict[str, Any],
) -> None:
    """Test that text with no comma-grouped numbers passes through unmodified."""
    text = "The year 2020 had 42 events."
    assert capture_helpers["convert_numbers_to_words"](text) == text


# ---------------------------------------------------------------------------
# refine_text
# ---------------------------------------------------------------------------


def test_refine_text_removes_footnote_markers(capture_helpers: dict[str, Any]) -> None:
    """Test that bracketed footnote markers are stripped."""
    result = capture_helpers["refine_text"]("Hello [1] world [22].")
    assert result == "Hello  world ."


def test_refine_text_truncates_at_related_marker(
    capture_helpers: dict[str, Any],
) -> None:
    """Test that text is cut off at the first 'Related:' occurrence."""
    result = capture_helpers["refine_text"]("Keep this. Related: some other stuff here")
    assert result == "Keep this. "


def test_refine_text_stops_at_exact_discard_line(
    capture_helpers: dict[str, Any],
) -> None:
    """Test that a line matching a discard marker exactly drops itself and all following lines."""
    result = capture_helpers["refine_text"]("Line one\nFor more\nLine three\n")
    assert result == "Line one\n"


def test_refine_text_partial_match_discard_line_is_not_truncated(
    capture_helpers: dict[str, Any],
) -> None:
    """
    Document a boundary footgun: discard-line matching requires an EXACT full-line match.

    ``line.strip() in discard_after_lines`` only matches when the entire
    stripped line equals "For more" or "THE LATEST NEWS" verbatim — a line
    like "For more info" (a very plausible real-world variant) does not
    trigger the cutoff at all, so trailing boilerplate leaks straight
    through into the narrated text.
    """
    text = "Line one\nFor more info\nLine three\n"
    assert capture_helpers["refine_text"](text) == text


def test_refine_text_stops_at_latest_news_marker_line(
    capture_helpers: dict[str, Any],
) -> None:
    """Test the second discard-line marker, 'THE LATEST NEWS', behaves like 'For more'."""
    result = capture_helpers["refine_text"]("Line one\nTHE LATEST NEWS\nLine three\n")
    assert result == "Line one\n"


def test_refine_text_converts_embedded_numbers(capture_helpers: dict[str, Any]) -> None:
    """Test that refine_text applies convert_numbers_to_words to the surviving text."""
    result = capture_helpers["refine_text"]("There are $1,300 million reasons.")
    assert result == "There are 1.3 billion dollars reasons."


def test_refine_text_no_discard_markers_present(
    capture_helpers: dict[str, Any],
) -> None:
    """Test that text without any discard marker or footnote passes through unchanged."""
    text = "Plain text with nothing special.\nSecond line.\n"
    assert capture_helpers["refine_text"](text) == text


# ---------------------------------------------------------------------------
# run_article_reader
# ---------------------------------------------------------------------------
#
# capture.py no longer hardcodes a venv python path or this project's absolute
# file path (Phase 2a); it launches `[sys.executable, "-m", "starling.reader"]`
# with CREATE_NEW_CONSOLE gated behind sys.platform == "win32" (that constant
# doesn't exist off Windows, so passing it unconditionally would crash on
# Linux/macOS). These were previously untested. `subprocess` and `sys` in the
# reduced namespace are the *same module objects* imported at test-module
# scope, since ast-exec'ing `import subprocess`/`import sys` binds the real
# modules -- so monkeypatching them here is visible inside run_article_reader.


def test_run_article_reader_windows_uses_new_console_flag_and_module_invocation(
    capture_helpers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test the win32 branch: CREATE_NEW_CONSOLE flag and exact argv."""
    monkeypatch.setattr(sys, "platform", "win32")
    captured: dict[str, Any] = {}

    def fake_popen(argv: list[str], **kwargs: Any) -> None:
        captured["argv"] = argv
        captured["kwargs"] = kwargs

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    capture_helpers["run_article_reader"]()

    assert captured["argv"] == [sys.executable, "-m", "starling.reader"]
    assert captured["kwargs"] == {
        "creationflags": subprocess.CREATE_NEW_CONSOLE,
    }


def test_run_article_reader_non_windows_uses_zero_creationflags(
    capture_helpers: dict[str, Any], monkeypatch: pytest.MonkeyPatch
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

    capture_helpers["run_article_reader"]()

    assert captured["argv"] == [sys.executable, "-m", "starling.reader"]
    assert captured["kwargs"] == {"creationflags": 0}
