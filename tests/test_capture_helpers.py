"""Behavioral tests for capture.py's pure text-processing helpers."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from starling.capture import (
    console_executable,
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
