import queue
import threading

import elevenlabslib

from utils import helper


class Synthesizer:
    def __init__(self, apiKey:str, outputDeviceName, ttsQueue:queue.Queue, voiceID, isPlaceHolder=False):
        self.eventQueue = queue.Queue()
        self.readyForPlaybackEvent = threading.Event()
        self.readyForPlaybackEvent.set()
        self.user = elevenlabslib.ElevenLabsUser(apiKey)

        if isPlaceHolder:
            self.placeHolderVoice = self.user.get_voice_by_ID(voiceID)
            self.placeHolderVoice.edit_settings(stability=0.65, similarity_boost=0.5)
            print(f"A new voice will be created. Eventually.")
        else:
            self.ttsVoice = self.user.get_voice_by_ID(voiceID)
            self.ttsVoice.edit_settings(stability=0.65, similarity_boost=0.5)
        self.outputDeviceInfo = helper.get_portaudio_device_info_from_name(outputDeviceName, "output")
        self.ttsQueue = ttsQueue
        #Let's go with some fairly conservative settings. There will be little emotion.
        #Can't really risk going lower given the clones may be low quality.
        self.interruptEvent = threading.Event()
        self.isRunning = threading.Event()
        self.isRunning.set()

    def set_voice(self, newVoiceID):
        self.ttsVoice = self.user.get_voice_by_ID(newVoiceID)

    def main_loop(self):
        threading.Thread(target=self.waitForPlaybackReady).start()  # Starts the thread that handles playback ordering.
        while True:
            try:
                prompt = self.ttsQueue.get(timeout=30)
            except queue.Empty:
                if self.interruptEvent.is_set():
                    print("Synthetizer main loop exiting...")
                    return
                continue
            if self.isRunning.is_set():
                print(f"Synthesizing prompt: {prompt}")
                self.synthesizeAndPlayAudio(prompt)

    def synthesizeAndPlayAudio(self, prompt) -> None:
        newEvent = threading.Event()
        self.eventQueue.put(newEvent)
        def startcallbackfunc():
            newEvent.wait()
        def endcallbackfunc():
            self.readyForPlaybackEvent.set()

        voice = self.ttsVoice
        if voice is None:
            voice = self.placeHolderVoice

        voice.generate_stream_audio(prompt=prompt, portaudioDeviceID=self.outputDeviceInfo["index"],
                                                streamInBackground=True,
                                                onPlaybackStart=startcallbackfunc,
                                                onPlaybackEnd=endcallbackfunc,
                                                latencyOptimizationLevel=4,
                                                model_id="eleven_multilingual_v1")

    def waitForPlaybackReady(self):
        while True:
            self.readyForPlaybackEvent.wait()
            self.readyForPlaybackEvent.clear()
            while True:
                try:
                    nextEvent = self.eventQueue.get(timeout=30)
                except queue.Empty:
                    if self.interruptEvent.is_set():
                        print("Synthetizer playback loop exiting...")
                        return
                    continue
                nextEvent.set()
                break