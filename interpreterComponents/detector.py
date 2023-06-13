import platform
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
        self.languageOverride = ""
        self.runLocal = runLocal

        if self.runLocal:
            if platform.system() == "Linux" or platform.system() == "Windows":
                self.model = faster_whisper.WhisperModel(modelSize, device="auto", compute_type="float16")
            else:
                self.model = faster_whisper.WhisperModel(modelSize, device="auto")
        else:
            openai.api_key = apiKey


        self.srRecognizer.energy_threshold = int(srSettings[0])
        self.srRecognizer.dynamic_energy_threshold = srSettings[1]
        self.srRecognizer.pause_threshold = float(srSettings[2])

        self.interruptEvent = threading.Event()
        self.isRunning = threading.Event()  #This one stops audio detection entirely when cleared.
        self.isRunning.set()

        global wRecognizer
        if wRecognizer is None:
            wRecognizer = Recognizer(runLocal, self.interruptEvent, modelSize, apiKey)
            threading.Thread(target=wRecognizer.main_loop).start()

        self.resultQueue = tlQueue
        self.cloneQueue:queue.Queue = cloneQueue


    def main_loop(self):
        GIL.acquire()
        with self.srMic as source:
            self.srRecognizer.adjust_for_ambient_noise(source)
            GIL.release()
            while True:
                self.isRunning.wait()  #Wait until we're running. This ensures that we don't accidentally record while muted.
                print("Detecting audio...")
                if self.interruptEvent.is_set():
                    print("Detector exiting...")
                    break
                try:
                    audio:sr.AudioData = self.srRecognizer.listen(source, timeout=30)
                except sr.WaitTimeoutError:
                    print("Audio rec interrupted")
                    continue
                if self.cloneQueue is not None:
                    self.cloneQueue.put(audio)

                print(f"Audio detected on {self.srMic.device_index}.")
                audioData = {"audio":audio,"queue":self.resultQueue}
                wRecognizer.audioQueue.put_nowait(audioData)

