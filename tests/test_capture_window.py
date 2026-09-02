"""
Behavioral tests for CaptureWindow and run_capture.

No test opens a visible window for longer than the test, enters a mainloop, or reads the
real clipboard -- CaptureWindow takes clipboard_read and on_close for exactly this. GUI
tests are gated by the tk_root fixture (tests/conftest.py), which skips on a headless
runner instead of failing.
"""

from __future__ import annotations

import contextlib
import inspect
import shutil
import tkinter as tk
from typing import TYPE_CHECKING

import pytest

import starling.capture
from starling.capture import CaptureWindow, refine_text
from starling.config import StarlingConfig, VoiceMode, ensure_directories

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


@pytest.fixture
def tmp_config(tmp_path: Path) -> StarlingConfig:
    """A StarlingConfig whose every path lives under tmp_path, with dirs created."""  # noqa: D401
    config = StarlingConfig(
        home_dir=tmp_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        archive_dir=tmp_path / "archive",
        credentials_path=None,
        language_code="en-US",
        voice_mode=VoiceMode.FIXED,
        voice_name="en-US-Chirp3-HD-Aoede",
        voice_pool=("en-US-Chirp3-HD-Aoede",),
        usage_log_path=tmp_path / "logs" / "usage.log",
        error_log_path=tmp_path / "logs" / "errors.log",
    )
    ensure_directories(config)
    return config


def _clipboard_sequence(*values: str) -> Callable[[], str]:
    """Return a clipboard_read stub that yields each value once, then repeats the last."""
    it = iter(values)
    last = values[-1] if values else ""

    def _read() -> str:
        nonlocal last
        with contextlib.suppress(StopIteration):
            last = next(it)
        return last

    return _read


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------


def test_capture_window_construction_builds_two_entries(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that construction builds two disabled Entry widgets under the given title."""
    window = CaptureWindow(tmp_config, root=tk_root, clipboard_read=lambda: "")

    assert isinstance(window.entry1, tk.Entry)
    assert isinstance(window.entry2, tk.Entry)
    assert tk_root.title() == "Fast Article Copy"


def test_capture_window_default_on_close_is_run_article_reader() -> None:
    """Test the __init__ signature's default on_close wiring, no Tk instance required."""
    default = inspect.signature(CaptureWindow.__init__).parameters["on_close"].default
    assert default is starling.capture.run_article_reader


# ---------------------------------------------------------------------------
# poll_clipboard_once
# ---------------------------------------------------------------------------


def test_poll_once_fills_first_slot(tk_root: tk.Tk, tmp_config: StarlingConfig) -> None:
    """Test that the first new clipboard text fills slot 1 and writes nothing."""
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", "First article body"),
    )

    result = window.poll_clipboard_once()

    assert result is None
    assert window.first_text == "First article body"
    assert window.second_text == ""
    assert list(tmp_config.input_dir.iterdir()) == []


def test_poll_twice_writes_the_pair(tk_root: tk.Tk, tmp_config: StarlingConfig) -> None:
    """Test that the second poll, once both slots are full, writes body-under-title."""
    body = "This is a long article body with plenty of characters in it."
    title = "Short Title"
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", body, title),
    )

    window.poll_clipboard_once()
    result = window.poll_clipboard_once()

    expected_path = tmp_config.input_dir / f"{title}.txt"
    assert result == expected_path
    assert expected_path.read_text(encoding="utf-8") == body
    assert window.first_text == ""
    assert window.second_text == ""


def test_poll_uses_shorter_text_as_filename_regardless_of_order(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that the shorter text is always the filename, even copied first."""
    short_text = "Short Title"
    long_text = "This is a much longer article body than the title text."
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", short_text, long_text),
    )

    window.poll_clipboard_once()
    result = window.poll_clipboard_once()

    expected_path = tmp_config.input_dir / f"{short_text}.txt"
    assert result == expected_path
    assert expected_path.read_text(encoding="utf-8") == long_text


def test_poll_sanitizes_the_filename(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that Windows-reserved characters are stripped from the derived filename."""
    short_text = 'a:b?c"d/e'
    long_text = "This is the long article body that becomes the file contents."
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", long_text, short_text),
    )

    window.poll_clipboard_once()
    result = window.poll_clipboard_once()

    assert result == tmp_config.input_dir / "abcde.txt"


def test_poll_ignores_unchanged_clipboard(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that an unchanged clipboard value does not fill the second slot."""
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", "Same text", "Same text"),
    )

    window.poll_clipboard_once()
    result = window.poll_clipboard_once()

    assert result is None
    assert window.second_text == ""


def test_poll_ignores_empty_clipboard(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that an empty clipboard is a true no-op: previous_clipboard is untouched."""
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("seed value", ""),
    )

    result = window.poll_clipboard_once()

    assert result is None
    assert window.previous_clipboard == "seed value"
    assert window.first_text == ""
    assert window.second_text == ""


def test_poll_applies_refine_text(tk_root: tk.Tk, tmp_config: StarlingConfig) -> None:
    """Test that poll_clipboard_once stores refine_text's output, not the raw clipboard."""
    raw = "Body [1] with $1,300 million.\nRelated: junk"
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", raw),
    )

    window.poll_clipboard_once()

    assert window.first_text == refine_text(raw)


def test_poll_clipboard_text_that_refines_to_empty_string_never_fills_slot(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """
    Document a boundary defect: a paste that refine_text reduces to "" is silently lost.

    ``poll_clipboard_once`` guards on the *raw* clipboard text ("if not text or text ==
    previous_clipboard"), but stores ``refine_text(text)`` into ``self.first_text``. A raw
    paste consisting only of a footnote marker like "[1]" refines down to "". Since "" is
    falsy, ``self.first_text`` still reads as "not filled" on the next poll -- the state
    machine can never advance past slot 1 for such input, even though a genuinely new,
    non-empty clipboard value was consumed and previous_clipboard was updated.
    """
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", "[1]", "[2]"),
    )
    assert refine_text("[1]") == ""
    assert refine_text("[2]") == ""

    result_one = window.poll_clipboard_once()
    assert result_one is None
    assert window.first_text == ""
    assert window.previous_clipboard == "[1]"

    result_two = window.poll_clipboard_once()
    assert result_two is None
    assert window.first_text == ""
    assert window.second_text == ""
    assert window.previous_clipboard == "[2]"


def test_save_pair_propagates_oserror_when_output_dir_missing(
    tk_root: tk.Tk, tmp_config: StarlingConfig
) -> None:
    """Test that a missing output directory at save time raises rather than being swallowed."""
    window = CaptureWindow(
        tmp_config,
        root=tk_root,
        clipboard_read=_clipboard_sequence("", "First body text here.", "Second title"),
    )
    window.poll_clipboard_once()
    shutil.rmtree(tmp_config.input_dir)

    with pytest.raises(FileNotFoundError):
        window.poll_clipboard_once()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


def test_close_launches_reader_then_destroys_root(tmp_config: StarlingConfig) -> None:
    """Test that close() calls on_close exactly once, then destroys the root."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - depends on the runner
        pytest.skip(f"no display available for Tk: {exc}")
    root.withdraw()

    calls: list[None] = []
    window = CaptureWindow(
        tmp_config,
        root=root,
        on_close=lambda: calls.append(None),
        clipboard_read=lambda: "",
    )

    window.close()

    assert len(calls) == 1
    # Destroying the root itself (not a child widget) tears down its Tcl interpreter,
    # so winfo_exists() raises TclError here rather than returning 0 -- either outcome
    # is proof the root no longer exists.
    with contextlib.suppress(tk.TclError):
        assert not root.winfo_exists()


# ---------------------------------------------------------------------------
# run_capture
# ---------------------------------------------------------------------------


def test_run_capture_returns_one_on_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a ConfigError from ensure_directories is reported and short-circuits."""

    def raiser(config: StarlingConfig) -> None:
        raise starling.capture.ConfigError("boom")

    monkeypatch.setattr(starling.capture, "ensure_directories", raiser)
    constructed: list[None] = []
    monkeypatch.setattr(
        starling.capture,
        "CaptureWindow",
        lambda *_args, **_kwargs: constructed.append(None),
    )

    result = starling.capture.run_capture(tmp_config)

    assert result == 1
    assert capsys.readouterr().out == "Error: boom\n"
    assert constructed == []


def test_run_capture_returns_one_when_no_display(
    monkeypatch: pytest.MonkeyPatch,
    tmp_config: StarlingConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test that a TclError from CaptureWindow construction is reported as no display."""

    def raiser(*args: object, **kwargs: object) -> None:
        raise tk.TclError("no display name")

    monkeypatch.setattr(starling.capture, "CaptureWindow", raiser)

    result = starling.capture.run_capture(tmp_config)

    assert result == 1
    assert "graphical display" in capsys.readouterr().out


def test_run_capture_returns_zero_and_runs_window_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_config: StarlingConfig
) -> None:
    """Test the success path: CaptureWindow is built with the config and window.run() is called."""
    calls: dict[str, object] = {}

    class FakeWindow:
        def __init__(self, config: StarlingConfig) -> None:
            calls["config"] = config

        def run(self) -> None:
            calls["ran"] = True

    monkeypatch.setattr(starling.capture, "CaptureWindow", FakeWindow)

    result = starling.capture.run_capture(tmp_config)

    assert result == 0
    assert calls["config"] is tmp_config
    assert calls["ran"] is True


def test_run_capture_lets_unexpected_exception_propagate(
    monkeypatch: pytest.MonkeyPatch, tmp_config: StarlingConfig
) -> None:
    """Test that only ConfigError is caught -- any other exception from ensure_directories propagates."""

    def raiser(config: StarlingConfig) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(starling.capture, "ensure_directories", raiser)

    with pytest.raises(RuntimeError, match="disk full"):
        starling.capture.run_capture(tmp_config)
