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


def run_article_reader() -> None:
    subprocess.Popen(
        [  # noqa: S607
            "python",
            r"C:\Users\user\dev\TTS\articleReader.py",
        ],
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


def refine_text(text: str) -> str:
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
