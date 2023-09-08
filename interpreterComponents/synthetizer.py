import logging
import queue
import threading
from dataclasses import dataclass

from elevenlabslib import GenerationOptions, PlaybackOptions, ElevenLabsModel

from utils import helper

@dataclass
class SynthesizerParams:
    apiKey: str
    outputDeviceName: str
    voiceID: str
    modelID: str
class Synthesizer:
    def __init__(self, params:SynthesizerParams, ttsQueue:queue.Queue):
        self.eventQueue = queue.Queue()
        self.readyForPlaybackEvent = threading.Event()
        self.readyForPlaybackEvent.set()
        self.user = helper.get_xi_user(params.apiKey)

        if " - " in params.modelID:
            # We need to cut out the modelID.
            params.modelID = params.modelID[params.modelID.index(" - ") + 3:]

        self.generationOptions = GenerationOptions(model=params.modelID, latencyOptimizationLevel=4, stability=0.5, similarity_boost=0.75)


        if " - " in params.voiceID:
            #We need to cut out the voiceID.
            params.voiceID = params.voiceID[params.voiceID.index(" - ") + 3:]


        self.ttsVoice = self.user.get_voice_by_ID(params.voiceID)
        self.ttsVoice.edit_settings(stability=0.65, similarity_boost=0.5)


        self.outputDeviceInfo = helper.get_portaudio_device_info_from_name(params.outputDeviceName, "output")
        self.ttsQueue = ttsQueue
        #Let's go with some fairly conservative settings. There will be little emotion.
        #Can't really risk going lower given the clones may be low quality.
        self.interruptEvent = threading.Event()
        self.isRunning = threading.Event()
        self.isRunning.set()

    def set_voice(self, newVoiceID):
        #Used by the interpreter to swap the voice to the cloned one
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

        playbackOptions = PlaybackOptions(runInBackground=True, portaudioDeviceID=self.outputDeviceInfo["index"], onPlaybackStart=startcallbackfunc, onPlaybackEnd=endcallbackfunc)
        self.ttsVoice.generate_stream_audio_v2(prompt=prompt, generationOptions=self.generationOptions, playbackOptions=playbackOptions)

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