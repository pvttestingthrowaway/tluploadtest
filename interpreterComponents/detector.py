import datetime
import gc
import logging
import os
import platform
import queue
import threading
from dataclasses import dataclass
from typing import Optional

import faster_whisper
import speech_recognition as sr
import openai

from utils import helper


@dataclass
class DetectorParams:
    inputDevice: str
    energy_threshold: int
    dynamic_energy_threshold: bool
    pause_threshold: float
    def __post_init__(self):
        if isinstance(self.energy_threshold, str):
            self.energy_threshold = int(self.energy_threshold)

        if isinstance(self.pause_threshold, str):
            self.pause_threshold = float(self.pause_threshold)
class Detector:
    GDL = threading.Lock()
    def __init__(self, params:DetectorParams, tlQueue:queue.Queue, audioQueue:queue.Queue, cloneQueue:Optional[queue.Queue]=None):
        self.microphoneInfo = helper.get_portaudio_device_info_from_name(params.inputDevice, "input")
        self.srMic = sr.Microphone(device_index=self.microphoneInfo["index"], sample_rate=int(self.microphoneInfo["default_samplerate"]))
        self.srRecognizer = sr.Recognizer()
        self.srRecognizer.non_speaking_duration = 0.5
        helper.logger.debug(f"Starting detector with settings: {params}")
        self.srRecognizer.energy_threshold = params.energy_threshold
        self.srRecognizer.dynamic_energy_threshold = params.dynamic_energy_threshold
        self.srRecognizer.pause_threshold = params.pause_threshold

        self.interruptEvent = threading.Event()
        self.isRunning = threading.Event()  #This one stops audio detection entirely when cleared.
        self.isRunning.set()
        self.recognizerData = None

        self.resultQueue = tlQueue
        self.cloneQueue = cloneQueue
        self.audioQueue = audioQueue


    def main_loop(self):
        Detector.GDL.acquire()
        with self.srMic as source:
            self.srRecognizer.adjust_for_ambient_noise(source)
            Detector.GDL.release()

            while True:
                self.isRunning.wait()  #Wait until we're running. This ensures that we don't accidentally record while muted.
                helper.logger.debug("Detecting audio...")
                try:
                    audio:sr.AudioData = self.srRecognizer.listen(source, timeout=20, phrase_time_limit=60)
                    #If you manage to speak a single sentence longer than 1 minute, congrats and f*** you.
                    #This is to force it to exit in cases with high background noise, which gets detected as speech.
                    #I have no idea what a better fix would be.
                except sr.WaitTimeoutError:
                    continue
                finally:
                    if self.interruptEvent.is_set():
                        helper.logger.debug("Detector exiting...")
                        break

                helper.logger.debug(f"Audio detected on {self.srMic.device_index}.")
                audioData = {
                    "audio":audio.get_wav_data(),
                    "queue":self.resultQueue,
                    "endTime": datetime.datetime.now()
                }

                if self.cloneQueue is not None:
                    audioData["clonequeue"] = self.cloneQueue

                if self.audioQueue is not None:
                    self.audioQueue.put_nowait(audioData)
                else:
                    helper.logger.warning("wRecognizer is none.")

