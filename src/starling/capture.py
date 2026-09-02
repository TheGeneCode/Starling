"""
The clipboard-capture window: watch the clipboard, refine what is copied, save articles.

Importing this module has no side effects. Construct CaptureWindow (or call run_capture)
to build the Tk window; nothing is created, polled, or written until then.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
import tkinter as tk
from importlib.resources import as_file, files
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pyperclip
from num2words import num2words

from starling.config import (
    ConfigError,
    StarlingConfig,
    ensure_directories,
    load_config,
)

if TYPE_CHECKING:
    from collections.abc import Callable

POLL_INTERVAL_MS: Final = 100
WINDOW_GEOMETRY: Final = "500x90"
WINDOW_TITLE: Final = "Fast Article Copy"
ENTRY_MAX_LENGTH: Final = 92
ICON_PACKAGE: Final = "starling"
ICON_RESOURCE: Final = ("resources", "starling.ico")


def make_filename_ready(filename: str) -> str:
    valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return re.sub(r"[^" + valid_chars + "]", "", filename)


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

    # Convert numbers to words
    text = convert_numbers_to_words(text)

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


def run_article_reader() -> None:
    """Launch the reader in a new process using the interpreter running this app."""
    creationflags = subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
    # S603: the argv is this app's own interpreter and module name, not user input.
    subprocess.Popen(  # noqa: S603
        [console_executable(), "-m", "starling", "read"],
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
    config = config if config is not None else load_config()
    try:
        ensure_directories(config)
    except ConfigError as exc:
        print(f"Error: {exc}")
        return 1
    try:
        window = CaptureWindow(config)
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
