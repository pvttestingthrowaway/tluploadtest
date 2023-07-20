import datetime
import gc
import io
import logging
import os
import platform
import queue
import sys
import threading

import faster_whisper
import openai
from faster_whisper.transcribe import TranscriptionInfo

from utils import helper


class Recognizer:
    def __init__(self, runLocal, modelSize=None, apiKey=None):
        self.runLocal = runLocal
        self.model = None
        if self.runLocal:
            if platform.system() == "Linux" or platform.system() == "Windows":
                self.model = faster_whisper.WhisperModel(modelSize, device="auto", compute_type="float16")
            else:
                self.model = faster_whisper.WhisperModel(modelSize, device="auto")
        else:
            openai.api_key = apiKey

        self.audioQueue = queue.Queue()
        self.interruptEvent = threading.Event()

    def main_loop(self):
        while True:
            wavBytes = None
            try:
                helper.logger.debug("Recognizer waiting...")
                audioData = self.audioQueue.get(timeout=10)
                wavBytes = audioData["audio"]
                resultQueue = audioData["queue"]
                endTime = audioData["endTime"]
                cloneQueue = None
                if "clonequeue" in audioData:
                    cloneQueue = audioData["clonequeue"]
            except queue.Empty:
                continue
            finally:
                if self.interruptEvent.is_set():
                    helper.logger.debug("Recognizer exiting...")
                    if self.model is not None:
                        del self.model  #This is just to ensure the allocated resources are free'd up correctly.
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                        gc.collect()
                    return

            helper.logger.debug("Running recognition...")
            if self.runLocal:
                segments, info = self.model.transcribe(io.BytesIO(wavBytes), beam_size=5, vad_filter=True)
                info:TranscriptionInfo
                info:dict = dict(info._asdict())
            else:
                with open("temp.wav","wb+") as fp:
                    fp.write(wavBytes)
                    fp.seek(0)
                    info:dict = openai.Audio.transcribe("whisper-1", fp, response_format="verbose_json")
                    segments = info["segments"]
                os.remove("temp.wav")
            duration = datetime.timedelta(seconds=info["duration"])
            audioLanguage = info["language"]
            recognizedText = ""
            for segment in segments:
                if segment.no_speech_prob < 0.70:
                    recognizedText += " " + segment.text.strip()
                else:
                    helper.logger.warning(f"Skipping segment {segment.text} with {segment.no_speech_prob*100}% chance of being non-speech")
            recognizedText = recognizedText.strip()

            hallucinated = False

            if recognizedText == "" or recognizedText == ".":
                hallucinated = True
            hallucinations = ["thank you for watching", "thanks for watching", "thank you so much for watching", "Please subscribe to the channel", "."]
            for hallucination in hallucinations:
                if hallucination.lower() in recognizedText.lower():
                    if len(recognizedText) < len(hallucination)+5:
                        hallucinated = True
            if hallucinated:
                helper.logger.warning("Hallucinating, ignoring it...")
                continue

            helper.logger.debug(f"recognizedText: {recognizedText}")

            resultQueue.put({
                    "text":recognizedText,
                    "lang":audioLanguage,
                    "startTime": endTime-duration,
                    "endTime": endTime
                })
            if cloneQueue is not None:
                cloneQueue.put(wavBytes)