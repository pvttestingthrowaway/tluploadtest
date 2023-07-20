import logging
import queue
import threading
from elevenlabslib import GenerationOptions, PlaybackOptions

from utils import helper


class Synthesizer:
    def __init__(self, apiKey:str, outputDeviceName, ttsQueue:queue.Queue, voiceID, isPlaceHolder=False):
        self.eventQueue = queue.Queue()
        self.readyForPlaybackEvent = threading.Event()
        self.readyForPlaybackEvent.set()
        self.user = helper.get_xi_user(apiKey)
        self.modelName = "eleven_multilingual_v1"

        modelNames = [model["name"] for model in self.user.get_available_models()]
        for name in modelNames:
            if "multilingual_v2" in name.lower():
                self.modelName = name

        self.generationOptions = GenerationOptions(model_id=self.modelName, latencyOptimizationLevel=4, stability=0.5, similarity_boost=0.75)

        self.ttsVoice = None

        if isPlaceHolder:
            self.placeHolderVoice = self.user.get_voice_by_ID(voiceID)
            self.placeHolderVoice.edit_settings(stability=0.65, similarity_boost=0.5)
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
                prompt = self.ttsQueue.get(timeout=10)
            except queue.Empty:
                continue
            finally:
                if self.interruptEvent.is_set():
                    helper.logger.debug("Synthetizer main loop exiting...")
                    return

            if self.isRunning.is_set():
                helper.logger.debug(f"Synthesizing prompt: {prompt}")
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

        playbackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=self.outputDeviceInfo["index"], onPlaybackStart=startcallbackfunc, onPlaybackEnd=endcallbackfunc)
        voice.generate_stream_audio_v2(prompt=prompt, generationOptions=self.generationOptions, playbackOptions=playbackOptions)

    def waitForPlaybackReady(self):
        while True:
            self.readyForPlaybackEvent.wait()
            self.readyForPlaybackEvent.clear()
            while True:
                try:
                    nextEvent = self.eventQueue.get(timeout=10)
                except queue.Empty:
                    continue
                finally:
                    if self.interruptEvent.is_set():
                        helper.logger.debug("Synthetizer playback loop exiting...")
                        return
                nextEvent.set()
                break