import datetime
import gc
import os
import platform
import queue
import threading
from typing import Optional

import faster_whisper
import speech_recognition as sr #TODO: Remember this has a pyaudio dependency.
import openai

from utils import helper
from interpreterComponents.recognizer import Recognizer

wRecognizer:Optional[Recognizer] = None
GIL = threading.Lock()
class Detector:
    def __init__(self, tlQueue, runLocal, inputDeviceName, srSettings:tuple, modelSize=None, apiKey=None, cloneQueue=None):
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

        global wRecognizer
        with GIL:
            if wRecognizer is None and (apiKey is not None or modelSize is not None):
                self.recognizerData = dict()
                helper.print_usage_info("Before recognizer init")
                wRecognizer = Recognizer(runLocal, modelSize, apiKey)
                self.recognizerData["thread"] = threading.Thread(target=wRecognizer.main_loop)
                self.recognizerData["event"] = wRecognizer.interruptEvent
                helper.print_usage_info("After recognizer init")
            elif wRecognizer is None and apiKey is None and modelSize is None:
                #UGLY UGLY UGLY Fake wRecognizer for settings testing.
                wRecognizer = type("", (), {"audioQueue":tlQueue})()

        self.resultQueue = tlQueue
        self.cloneQueue:queue.Queue = cloneQueue


    def main_loop(self):
        GIL.acquire()
        with self.srMic as source:
            self.srRecognizer.adjust_for_ambient_noise(source)
            GIL.release()
            global wRecognizer
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
                    if self.interruptEvent.is_set():
                        print("Detector exiting...")
                        del wRecognizer
                        gc.collect()
                        wRecognizer = None
                        break
                    continue

                print(f"Audio detected on {self.srMic.device_index}.")
                audioData = {
                    "audio":audio.get_wav_data(),
                    "queue":self.resultQueue,
                    "endTime": datetime.datetime.now()
                }

                if self.cloneQueue is not None:
                    audioData["clonequeue"] = self.cloneQueue
                if wRecognizer is not None:
                    wRecognizer.audioQueue.put_nowait(audioData)
                else:
                    print("wRecognizer is none.")

