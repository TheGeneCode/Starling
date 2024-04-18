import tkinter as tk
from tkinter import messagebox
import pyperclip
from os import path

# Create the main window
root = tk.Tk()
root.geometry("500x90")
root.title("Fast Article Copy")
root.attributes("-topmost", True)

# Define variables to store clipboard content
previous_clipboard = (
    pyperclip.paste()
)  # set to clipboard at launch so initial contents aren't copied
var1 = tk.StringVar()
var2 = tk.StringVar()
outputFolderPath = r"C:\Users\user\scripts\python\TTS\input"


def shorten_text(text, max_length=92):
    """
    Shortens text to a maximum length, adding ellipsis if truncated.

    Args:
        text: The text to shorten.
        max_length: The maximum allowed length (default: 92).

    Returns:
        The shortened text with ellipsis if it exceeds the limit.
    """
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def update_entry(entry, text):
    """
    Updates the content of an entry widget.

    Args:
        entry: The entry widget to update.
        text: The text to insert into the entry.
    """
    entry.config(state="normal")  # Allow editing temporarily
    entry.delete(0, tk.END)  # Clear existing content
    entry.insert(0, shorten_text(text))  # Insert new content
    entry.config(state="disabled")  # Disable editing again


def check_clipboard():
    global previous_clipboard  # Access global variable
    text = pyperclip.paste()  # Get clipboard content
    if text and text != previous_clipboard:  # Check for new content
        previous_clipboard = text  # Update previous content
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
            outputFilepath = path.join(outputFolderPath, f"{short_text}.txt")
            with open(outputFilepath, "x", encoding="utf-8") as f:
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
