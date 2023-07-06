import datetime
import gc
import os
import platform
import queue
import threading
from typing import Optional

import faster_whisper
import speech_recognition as sr
import openai

from utils import helper

class Detector:
    GDL = threading.Lock()
    def __init__(self, tlQueue: queue.Queue, inputDeviceName:str, srSettings:tuple, audioQueue: queue.Queue, cloneQueue=None):
        self.microphoneInfo = helper.get_portaudio_device_info_from_name(inputDeviceName, "input")
        self.srMic = sr.Microphone(device_index=self.microphoneInfo["index"], sample_rate=int(self.microphoneInfo["default_samplerate"]))
        self.srRecognizer = sr.Recognizer()
        self.srRecognizer.non_speaking_duration = 0.5
        print(srSettings)
        self.srRecognizer.energy_threshold = int(srSettings[0])
        self.srRecognizer.dynamic_energy_threshold = srSettings[1]
        self.srRecognizer.pause_threshold = float(srSettings[2])

        self.interruptEvent = threading.Event()
        self.isRunning = threading.Event()  #This one stops audio detection entirely when cleared.
        self.isRunning.set()
        self.recognizerData = None

        self.resultQueue = tlQueue
        self.cloneQueue:queue.Queue = cloneQueue
        self.audioQueue = audioQueue


    def main_loop(self):
        Detector.GDL.acquire()
        with self.srMic as source:
            self.srRecognizer.adjust_for_ambient_noise(source)
            Detector.GDL.release()

            while True:
                self.isRunning.wait()  #Wait until we're running. This ensures that we don't accidentally record while muted.
                print("Detecting audio...")
                try:
                    audio:sr.AudioData = self.srRecognizer.listen(source, timeout=20, phrase_time_limit=60)
                    #If you manage to speak a single sentence longer than 1 minute, congrats and f*** you.
                    #This is to force it to exit in cases with high background noise, which gets detected as speech.
                    #I have no idea what a better fix would be.
                except sr.WaitTimeoutError:
                    print("Audio rec interrupted")
                    continue
                finally:
                    if self.interruptEvent.is_set():
                        print("Detector exiting...")
                        break

                print(f"Audio detected on {self.srMic.device_index}.")
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
                    print("wRecognizer is none.")

