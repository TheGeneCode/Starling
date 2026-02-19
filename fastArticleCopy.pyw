"""
A clipboard monitoring Tkinter application for quickly capturing and saving article text.

This script creates a GUI window that monitors clipboard changes, refines and stores up to two copied texts,
and automatically saves the longer text to a file in a specified folder when both slots are filled.
It also launches an external article reader script upon window close.
"""

import re
import subprocess
import tkinter as tk
from pathlib import Path

import pyperclip
from num2words import num2words


def run_article_reader() -> None:
    venv_python = Path(r"C:\Users\user\dev\TTS\.venv\Scripts\python.exe")
    subprocess.Popen(  # noqa: S603
        [
            str(venv_python),
            r"C:\Users\user\dev\TTS\articleReader.py",
        ],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        cwd=str(
            Path(__file__).parent,
        ),  # ensure tts_usage.log is created in project folder
    )


def on_closing() -> None:
    run_article_reader()
    root.destroy()


# Create the main window
root = tk.Tk()
root.geometry("500x90")
root.title("Fast Article Copy")
root.attributes("-topmost", True)  # noqa: FBT003
root.protocol("WM_DELETE_WINDOW", on_closing)

# Define variables to store clipboard content
previous_clipboard = (
    pyperclip.paste()
)  # set to clipboard at launch so initial contents aren't copied
var1 = tk.StringVar()
var2 = tk.StringVar()
output_folder_path = r"C:\Users\user\dev\TTS\input"


def make_filename_ready(filename: str) -> str:
    valid_chars = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return re.sub(r"[^" + valid_chars + "]", "", filename)


def convert_numbers_to_words(text: str) -> str:
    """
    Convert numbers to words in the text, handling currency scaling and formatting.
    """
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
            if words.endswith(", zero cents"):
                words = words[:-12]
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
    text = re.sub(
        r"(?<![\$\d])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\d])", number_to_words, text
    )

    return text


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


def shorten_text(text: str, max_length: int = 92) -> str:
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


def update_entry(entry: tk.Entry, text: str) -> None:
    """
    Update the content of an entry widget.

    Args:
        entry: The entry widget to update.
        text: The text to insert into the entry.
    """
    entry.config(state="normal")  # Allow editing temporarily
    entry.delete(0, tk.END)  # Clear existing content
    entry.insert(0, shorten_text(text))  # Insert new content
    entry.config(state="disabled")  # Disable editing again


def check_clipboard() -> None:
    global previous_clipboard  # Access global variable  # noqa: PLW0603
    text = pyperclip.paste()  # Get clipboard content
    if text and text != previous_clipboard:  # Check for new content
        previous_clipboard = text  # Update previous content
        text = refine_text(text)
        if not var1.get():
            var1.set(text)
            update_entry(entry1, text)
        elif not var2.get():
            var2.set(text)
            update_entry(entry2, text)
        # Check if both variables have text and save the longer one
        if var1.get() and var2.get():
            long_text, short_text = (
                (var1.get(), var2.get())
                if len(var1.get()) > len(var2.get())
                else (var2.get(), var1.get())
            )
            short_text = make_filename_ready(short_text)
            output_file_path = Path(output_folder_path) / f"{short_text}.txt"
            with output_file_path.open("w", encoding="utf-8") as f:
                f.write(long_text)
            # Clear variables
            var1.set("")
            var2.set("")
            update_entry(entry1, "")
            update_entry(entry2, "")
    # Schedule continuous checking for clipboard changes
    root.after(100, check_clipboard)  # Check every 100 milliseconds


# Create labels and entry fields for variables
label1 = tk.Label(root, text="Variable 1:")
label1.pack(anchor="w")
entry1 = tk.Entry(root, textvariable=shorten_text(var1.get()), state="disabled")
entry1.pack(anchor="w", fill=tk.X)

label2 = tk.Label(root, text="Variable 2:")
label2.pack(anchor="w")
entry2 = tk.Entry(root, textvariable=shorten_text(var2.get()), state="disabled")
entry2.pack(anchor="w", fill=tk.X)

# Keep the window open
check_clipboard()
root.mainloop()
