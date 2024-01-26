from gtts import gTTS
from glob import glob
from os import path, makedirs, remove
from time import sleep
from threading import Thread, Event


def spinner(shouldSpin):
    chars = "-\|/"
    while shouldSpin.is_set():
        for char in chars:
            print(f"Speaking... {char}", end="\r")
            sleep(0.1)


if __name__ == "__main__":
    inputFolderPath = r"C:\Users\user\scripts\python\TTS\input\*.txt"
    outputFolderPath = r"C:\Users\user\scripts\manual podcasts"

    if not path.exists(outputFolderPath):
        makedirs(outputFolderPath)

    inputPaths = [path for path in glob(inputFolderPath)]
    if inputPaths:
        for filepath in glob(inputFolderPath):
            with open(filepath, "r", encoding="utf8") as file:
                filename = path.basename(filepath).split(".")[0]
                outputFilepath = path.join(outputFolderPath, f"{filename}.mp3")
                print(f"Starting {filename}")
                # thread for the spinner
                shouldSpin = Event()
                shouldSpin.set()
                spinnerThread = Thread(target=spinner, args=(shouldSpin,))
                spinnerThread.start()
                # slow task
                tts = gTTS(text=file.read(), tld="us")
                tts.save(outputFilepath)
                # close spinner thread
                shouldSpin.clear()
                spinnerThread.join()
                print(f"Finished")
                remove(filepath)
        print("All files completed.")
    else:
        print("No text files found.")
