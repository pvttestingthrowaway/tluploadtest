import io
import os
import platform
import queue
import threading

import faster_whisper
import openai
from PyQt6.QtCore import pyqtSignal


class Recognizer:
    def __init__(self, runLocal, interruptEvent:threading.Event, modelSize=None, apiKey=None):
        self.runLocal = runLocal

        if self.runLocal:
            if platform.system() == "Linux" or platform.system() == "Windows":
                self.model = faster_whisper.WhisperModel(modelSize, device="auto", compute_type="float16")
            else:
                self.model = faster_whisper.WhisperModel(modelSize, device="auto")
        else:
            openai.api_key = apiKey

        self.audioQueue = queue.Queue()
        self.interruptEvent = interruptEvent


    def main_loop(self):
        while True:
            try:
                audioData = self.audioQueue.get(timeout=5)
                audio = audioData["audio"]
                resultQueue = audioData["queue"]
                cloneQueue = None
                if "clonequeue" in audioData:
                    cloneQueue = audioData["clonequeue"]
            except queue.Empty:
                if self.interruptEvent.is_set():
                    print("Recognizer exiting...")
                    return
                continue

            print("Running recognition...")
            if self.runLocal:
                segments, info = self.model.transcribe(io.BytesIO(audio.get_wav_data()), beam_size=5)
                audioLanguage = info.language
                recognizedText = ""
                for segment in segments:
                    recognizedText += " " + segment.text
                recognizedText = recognizedText.strip()
            else:
                with open("temp.wav","wb+") as fp:
                    fp.write(audio.get_wav_data())
                    fp.seek(0)
                    recognizedText = openai.Audio.transcribe("whisper-1", fp, response_format="verbose_json")
                    audioLanguage = recognizedText.language
                    recognizedText = recognizedText.text
                os.remove("temp.wav")

            print(f"recognizedText: {recognizedText}")
            if recognizedText == "":
                continue    #Had no actual text.
            resultQueue.put({
                    "text":recognizedText,
                    "lang":audioLanguage
                })
            if cloneQueue is not None:
                cloneQueue.put(audio)