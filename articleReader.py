"""Processes all .txt files in the specified input directory by removing citations, converting the text to speech using KittenTTS, and saving the resulting audio as .mp3 files in the output directory. Displays a spinner animation during processing, handles file overwrites with user confirmation, logs errors, and moves processed files to an archive directory."""

import itertools

# from TTS.api import TTS
# import torch
# import subprocess
import logging
import re
import shutil
import time
from pathlib import Path
from threading import Event, Thread

from gtts import gTTS
from gtts.tts import gTTSError

# from kittentts import KittenTTS


def spinner(should_spin: Event) -> None:
    """
    Display a spinning animation on the console while a task is being executed.

    Args: should_spin (Event): An Event object that controls whether the spinner animation should continue spinning or stop.
    """
    chars = itertools.cycle("-\|/")  # noqa: W605
    while should_spin.is_set():
        char = next(chars)
        print(f"Speaking... {char}", end="\r")
        time.sleep(0.1)


def remove_citations(text: str) -> str:
    citations_regex = r"\([^\)]+(?:,\s*\d{4}(?:[a-zA-Z]?)?(?:,\s*p\.\s*\d+)?)+\)"
    return re.sub(citations_regex, "", text)


if __name__ == "__main__":
    logging.basicConfig(
        filename="logfile.txt",
        level=logging.ERROR,
        format="%(asctime)s %(message)s",
    )
    logger = logging.getLogger(__name__)

    output_folder_path = Path(
        r"C:\Users\user\scripts\manual podcasts",
    )
    archive_folder_path = Path(
        r"C:\Users\user\dev\TTS\archive",
    )
    input_folder_path = Path(
        r"C:\Users\user\dev\TTS\input",
    )

    # Ensure output and archive directories exist
    output_folder_path.mkdir(parents=True, exist_ok=True)
    archive_folder_path.mkdir(parents=True, exist_ok=True)

    input_paths = list(input_folder_path.glob("*.txt"))
    if input_paths:
        for filepath in input_paths:
            with filepath.open("r", encoding="utf8") as file:
                filename = filepath.stem
                output_file_path = output_folder_path / f"{filename}.wav"
                if output_file_path.exists():
                    overwrite = input(
                        f"The file {output_file_path} already exists. Do you want to overwrite it? (y/n): ",
                    )
                    if overwrite.lower() != "y":
                        continue
                print(f"Starting {filename}")
                # thread for the spinner
                should_spin = Event()
                should_spin.set()
                spinner_thread = Thread(target=spinner, args=(should_spin,))
                spinner_thread.start()
                # slow task
                try:
                    text = file.read()
                    text = remove_citations(text)
                    # kittenTTS - need to wait for chunking to be implemented
                    # m = KittenTTS("KittenML/kitten-tts-nano-0.1")
                    # audio = m.generate(text, voice="expr-voice-2-f")
                    # import soundfile as sf

                    # sf.write(str(output_file_path), audio, 24000)

                    # uses google API, not terrible
                    tts = gTTS(text=text, tld="us")
                    tts.save(output_file_path)
                    # uses on client AI voice
                    # device = "cuda" if torch.cuda.is_available() else "cpu"
                    # tts = TTS("tts_models/en/ljspeech/tacotron2-DDC_ph").to(device)
                    # tts.tts_to_file(text=file.read(), file_path=outputFilepath)
                    shutil.move(
                        filepath,
                        str(Path(archive_folder_path) / Path(filepath).name),
                    )
                except (FileNotFoundError, PermissionError, OSError) as e:
                    print(f"File error while processing {filepath}: {e!s}")
                except gTTSError as e:
                    print(f"TTS error while processing {filepath}: {e!s}")
                except Exception:
                    logger.exception("Unexpected error while processing %s", filepath)
                    print(
                        f"Unexpected error occurred while processing {filepath}. Check logfile.txt for details.",
                    )
                # close spinner thread
                should_spin.clear()
                spinner_thread.join()
                print("Finished")
        print("All files completed.")
    else:
        print("No text files found.")
