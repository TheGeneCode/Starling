import shutil
import itertools
import time
from gtts import gTTS
from glob import glob
from os import path, makedirs, remove
from threading import Thread, Event


def spinner(shouldSpin: Event) -> None:
    """Displays a spinning animation on the console while a task is being executed.

    Args:
        shouldSpin (Event): An Event object that controls whether the spinner animation should continue spinning or stop.
    """
    chars = itertools.cycle("-\|/")
    while shouldSpin.is_set():
        char = next(chars)
        print(f"Speaking... {char}", end="\r")
        time.sleep(0.1)


if __name__ == "__main__":
    inputFolderPath = r"C:\Users\user\scripts\python\TTS\input\*.txt"
    outputFolderPath = r"C:\Users\user\scripts\manual podcasts"
    archiveFolderPath = r"C:\Users\user\scripts\archive"

    if not path.exists(outputFolderPath):
        makedirs(outputFolderPath)

    if not path.exists(archiveFolderPath):
        makedirs(archiveFolderPath)

    inputPaths = [path for path in glob(inputFolderPath)]
    if inputPaths:
        for filepath in glob(inputFolderPath):
            with open(filepath, "r", encoding="utf8") as file:
                filename = path.basename(filepath).split(".")[0]
                outputFilepath = path.join(outputFolderPath, f"{filename}.mp3")
                if path.exists(outputFilepath):
                    overwrite = input(
                        f"The file {outputFilepath} already exists. Do you want to overwrite it? (y/n): "
                    )
                    if overwrite.lower() != "y":
                        continue
                print(f"Starting {filename}")
                # thread for the spinner
                shouldSpin = Event()
                shouldSpin.set()
                spinnerThread = Thread(target=spinner, args=(shouldSpin,))
                spinnerThread.start()
                # slow task
                try:
                    tts = gTTS(text=file.read(), tld="us")
                    tts.save(outputFilepath)
                except Exception as e:
                    print(f"Error occurred while processing {filepath}: {str(e)}")
                # close spinner thread
                shouldSpin.clear()
                spinnerThread.join()
                print(f"Finished")
            shutil.move(filepath, path.join(archiveFolderPath, path.basename(filepath)))
        print("All files completed.")
    else:
        print("No text files found.")
