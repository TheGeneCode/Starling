"""
The clipboard-capture window: watch the clipboard, refine what is copied, save articles.

Importing this module has no side effects. Construct CaptureWindow (or call run_capture)
to build the Tk window; nothing is created, polled, or written until then. tkinter itself
is optional at import time -- it ships with the OS/interpreter rather than pip, so a
uv-managed interpreter (CI's ubuntu-latest runners, for one) may not have it. ``tk`` is
None in that case; only the GUI entry points (run_capture, CaptureWindow, update_entry,
apply_window_icon) need it, and they fail with a clear message instead of at import time.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
from functools import partial
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pyperclip

from starling.config import (
    ConfigError,
    StarlingConfig,
    ensure_directories,
    load_config,
)

try:
    import tkinter as tk
except ImportError:
    tk = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from collections.abc import Callable

POLL_INTERVAL_MS: Final = 100
WINDOW_GEOMETRY: Final = "500x90"
WINDOW_TITLE: Final = "Starling Capture"
ENTRY_MAX_LENGTH: Final = 92
ICON_PACKAGE: Final = "starling"
ICON_RESOURCE: Final = ("resources", "starling.ico")


def make_filename_ready(filename: str) -> str:
    valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return re.sub(r"[^" + valid_chars + "]", "", filename)


def refine_text(text: str) -> str:
    text = re.sub(r"\[\d+\]", "", text)
    discard_after_strings = ["Related:"]
    discard_after_lines = ["For more", "THE LATEST NEWS"]
    # Find the first occurrence of any discard string in the text
    discard_index = min(
        [text.find(s) for s in discard_after_strings],
    )  # -1 if none found
    if discard_index >= 0:
        text = text[:discard_index]

    # Search for whole lines that are not wanted and discard everything after
    lines = text.splitlines(keepends=True)
    text = ""
    for line in lines:
        if line.strip() in discard_after_lines:
            break
        text += line

    return text


def shorten_text(text: str, max_length: int = ENTRY_MAX_LENGTH) -> str:
    """
    Shorten text to a maximum length, adding ellipsis if truncated.

    Args:
        text: The text to shorten.
        max_length: The maximum allowed length (default: 92).

    Returns:
        The shortened text with ellipsis if it exceeds the limit.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def console_executable() -> str:
    """
    Return an interpreter that owns a console.

    Launching the reader from pythonw.exe (the historical .pyw entry point) gives it
    CREATE_NEW_CONSOLE but no console to write to, so the spinner and the overwrite
    prompt go nowhere. Swap in the sibling python.exe when there is one.
    """
    executable = Path(sys.executable)
    if sys.platform == "win32" and executable.name.lower() == "pythonw.exe":
        candidate = executable.with_name("python.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable


def run_article_reader(*, confirm: bool = False) -> None:
    """
    Launch the reader in a new process using the interpreter running this app.

    ``confirm`` appends ``--confirm``, so the child prints the dry-run cost report and
    asks before it bills anything. The prompt has to live in the child: this is a new
    console, and the Tk window is already being torn down when this is called.
    """
    creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    argv = [console_executable(), "-m", "starling", "read"]
    if confirm:
        argv.append("--confirm")
    # S603: the argv is this app's own interpreter and module name, not user input.
    subprocess.Popen(  # noqa: S603
        argv,
        creationflags=creationflags,
    )


def update_entry(entry: tk.Entry, text: str) -> None:
    """
    Update the content of a disabled entry widget.

    Args:
        entry: The entry widget to update.
        text: The text to insert into the entry.
    """
    entry.config(state="normal")
    entry.delete(0, tk.END)
    entry.insert(0, shorten_text(text))
    entry.config(state="disabled")


def apply_window_icon(root: tk.Tk) -> None:
    """
    Give the window a title-bar and taskbar icon, or leave Tk's default in place.

    ``iconbitmap`` is Windows-only -- it raises TclError on every other platform -- and
    the packaged resource could be missing from an unusually built wheel. Neither is a
    reason to refuse to open the capture window, so both are swallowed.

    ``as_file`` is a no-op passthrough for a normal directory install, returning the real
    path; it only materializes a temporary file for a zipimport, which Starling does not
    use. Tk reads the .ico eagerly inside ``iconbitmap``, so the path only has to be
    valid for the duration of the ``with`` block either way.
    """
    with contextlib.suppress(OSError, tk.TclError):
        resource = files(ICON_PACKAGE).joinpath(*ICON_RESOURCE)
        with as_file(resource) as icon_path:
            root.iconbitmap(str(icon_path))


class CaptureWindow:
    """
    The clipboard-capture window.

    Constructing this builds Tk widgets; `run()` starts polling and blocks in the
    mainloop. `poll_clipboard_once()` is the whole state machine and is callable
    directly, so the save behavior is testable without a mainloop.
    """

    def __init__(
        self,
        config: StarlingConfig,
        *,
        root: tk.Tk | None = None,
        poll_interval_ms: int = POLL_INTERVAL_MS,
        on_close: Callable[[], None] = run_article_reader,
        clipboard_read: Callable[[], str] = pyperclip.paste,
    ) -> None:
        self.config = config
        self.output_dir = config.input_dir
        self.poll_interval_ms = poll_interval_ms
        self.on_close = on_close
        self.clipboard_read = clipboard_read
        # Seed from the clipboard at launch so its existing contents aren't captured.
        self.previous_clipboard = clipboard_read()
        self.first_text = ""
        self.second_text = ""
        self.root = tk.Tk() if root is None else root
        self._build_ui()

    def _build_ui(self) -> None:
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.title(WINDOW_TITLE)
        apply_window_icon(self.root)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        tk.Label(self.root, text="Variable 1:").pack(anchor="w")
        self.entry1 = tk.Entry(self.root, state="disabled")
        self.entry1.pack(anchor="w", fill=tk.X)

        tk.Label(self.root, text="Variable 2:").pack(anchor="w")
        self.entry2 = tk.Entry(self.root, state="disabled")
        self.entry2.pack(anchor="w", fill=tk.X)

    def run(self) -> None:
        """Start polling and block until the window is closed."""
        self.check_clipboard()
        self.root.mainloop()

    def check_clipboard(self) -> None:
        """Poll once, then reschedule. This is the only method that touches the event loop."""
        self.poll_clipboard_once()
        self.root.after(self.poll_interval_ms, self.check_clipboard)

    def poll_clipboard_once(self) -> Path | None:
        """
        Consume one clipboard change. Returns the article file written, if a pair completed.

        The first new clipboard text fills slot 1, the second fills slot 2. Once both are
        filled the longer one is saved as the article body and the shorter one, made
        filename-safe, becomes the filename; both slots are then cleared.
        """
        text = self.clipboard_read()
        if not text or text == self.previous_clipboard:
            return None
        self.previous_clipboard = text

        text = refine_text(text)
        if not self.first_text:
            self.first_text = text
            update_entry(self.entry1, text)
        elif not self.second_text:
            self.second_text = text
            update_entry(self.entry2, text)

        if self.first_text and self.second_text:
            return self._save_pair()
        return None

    def _save_pair(self) -> Path:
        long_text, short_text = (
            (self.first_text, self.second_text)
            if len(self.first_text) > len(self.second_text)
            else (self.second_text, self.first_text)
        )
        output_path = self.output_dir / f"{make_filename_ready(short_text)}.txt"
        output_path.write_text(long_text, encoding="utf-8")
        self.first_text = ""
        self.second_text = ""
        update_entry(self.entry1, "")
        update_entry(self.entry2, "")
        return output_path

    def close(self) -> None:
        """WM_DELETE_WINDOW handler: launch the reader, then tear the window down."""
        self.on_close()
        self.root.destroy()


def run_capture(config: StarlingConfig | None = None) -> int:
    """Open the capture window and block until it closes. Returns a process exit code."""
    if tk is None:
        print(
            "Error: could not open the capture window. Starling's capture UI needs "
            "tkinter, which is not installed for this Python interpreter.",
        )
        return 1
    config = config if config is not None else load_config()
    try:
        ensure_directories(config)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1
    try:
        window = CaptureWindow(
            config,
            on_close=partial(run_article_reader, confirm=config.capture_confirm),
        )
    except tk.TclError as exc:
        print(
            "Error: could not open the capture window. Starling's capture UI needs a "
            f"graphical display: {exc}",
        )
        return 1
    window.run()
    return 0


if __name__ == "__main__":
    sys.exit(run_capture())
