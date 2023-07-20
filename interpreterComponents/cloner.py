import logging
import os
import queue
import threading
from typing import Union

import requests
import io

from PyQt6.QtCore import pyqtSignal
from elevenlabslib import ElevenLabsUser
from pydub import AudioSegment, effects
from audoai.noise_removal import NoiseRemovalClient

from speech_recognition import AudioData

from utils import helper

requiredDuration = 180

class Cloner:
    def __init__(self, cloneQueue, xiApikey, voiceName, audoApiKey=None):
        self.cloneQueue = cloneQueue
        self.voiceName = voiceName
        self.user = helper.get_xi_user(xiApikey)
        self.noiseRemoval = None if audoApiKey is None or audoApiKey == "" else helper.get_audo_client(apiKey=audoApiKey, exitOnFail=True)
        self.interruptEvent = threading.Event()
        self.processedAudioQueue = queue.Queue()
        self.totalDuration:float = 0.0
        self.durationLock = threading.Lock()
        self.dataComplete = False

    def main_loop(self, cloneProgressSignal:pyqtSignal):
        while True:
            try:
                wavData:Union[bytes,str] = self.cloneQueue.get(timeout=10)
            except queue.Empty:
                continue
            finally:
                if self.interruptEvent.is_set():
                    helper.logger.debug("Cloner main loop exiting...")
                    return None
            helper.logger.debug("Recieved audioSegment to clean.")

            if isinstance(wavData, bytes):
                threading.Thread(target=self.clean_audio, args=(wavData, cloneProgressSignal)).start()
            else:
                helper.logger.debug("We have enough audio data to create a clone.")
                cloneProgressSignal.emit(f"PROCESSING")

                finalizedAudioBytes = list()
                finalizedAudio = AudioSegment.empty()
                silence = AudioSegment.silent(500)
                sizeLimit = 9*1024*1024
                for audio in iter(self.processedAudioQueue.get, None):
                    audio:AudioSegment
                    buffer = io.BytesIO()
                    temp_audio = finalizedAudio + audio + silence
                    temp_audio.export(buffer, format="mp3")
                    if buffer.getbuffer().nbytes > sizeLimit:
                        # If the size limit is exceeded, don't append the audio and save the finalized_audio
                        finalizedBytes = io.BytesIO()
                        finalizedAudio.export(finalizedBytes, format="mp3")
                        finalizedBytes.seek(0)
                        finalizedAudioBytes.append(finalizedBytes.read())
                        # Reset the finalized_audio with the current audio and silence
                        finalizedAudio = audio + silence
                    else:
                        # If the size limit is not exceeded, add the audio to the finalized_audio
                        finalizedAudio = temp_audio

                if finalizedAudio.duration_seconds > 0:
                    finalizedBytes = io.BytesIO()
                    finalizedAudio.export(finalizedBytes, format="mp3")
                    finalizedBytes.seek(0)
                    finalizedAudioBytes.append(finalizedBytes.read())

                samplesDict = dict()
                for index,audioBytes in enumerate(finalizedAudioBytes):
                    samplesDict[f"{self.voiceName}_sample_{index}.mp3"] = audioBytes

                newVoiceID = self.user.clone_voice_bytes(self.voiceName, samplesDict).voiceID
                cloneProgressSignal.emit(f"COMPLETE")
                return newVoiceID

    def clean_audio(self, wavBytes:bytes, cloneProgressSignal:pyqtSignal):

        #TODO: Remove the saving stuff. It's purely for testing.
        i = 0
        while os.path.exists(f"Original_{i}.wav"):
            i += 1

        with open(f"Original_{i}.wav", "wb") as fp:
            fp.write(wavBytes)

        #TODO: REMOVE THIS DEBUG INSTANT CLONING. DEBUG BYPASS.
        if os.path.exists(f"Prefab-_0.wav"):
            i = 0
            while os.path.exists(f"Prefab-_{i}.wav"):
                with open(f"Prefab-_{i}.wav", "rb") as fp:
                    finalAudio = AudioSegment.from_file_using_temporary_files(fp)
                    print(f"Adding {i} to final queue (DEBUG)")
                    with self.durationLock:
                        self.processedAudioQueue.put(finalAudio)
                        self.totalDuration += finalAudio.duration_seconds
                        cloneProgressSignal.emit(f"{self.totalDuration}")
                        if self.totalDuration > requiredDuration and not self.dataComplete:
                            print(f"After {i} we have enough data to begin.")
                            self.dataComplete = True
                            self.cloneQueue.put("dataComplete")
                            self.processedAudioQueue.put(None)  # Mark the end of the processed audios
                            return
                i += 1


        helper.logger.debug(f"Processing audio {i}.")
        audio = AudioSegment.from_file_using_temporary_files(io.BytesIO(wavBytes))
        audio = effects.normalize(audio)
        target_dBFS = -20
        normalizedAudio:AudioSegment = audio.apply_gain(target_dBFS - audio.dBFS)

        with open(f"Normalized_{i}.wav", "wb") as fp:
            normalizedAudio.export(fp, format="wav")

        helper.logger.debug(f"Normalized audio {i}.")
        if self.noiseRemoval is not None:
            helper.logger.debug(f"Removing noise from {i}")
            mp3Bytes = io.BytesIO()
            #Turn into mp3 for smaller upload filesize
            normalizedAudio.export(mp3Bytes, format="mp3")
            mp3Bytes.seek(0)

            try:
                result = self.noiseRemoval.process(mp3Bytes, input_extension="mp3", output_extension="mp3")
                cleanedAudio = AudioSegment.from_file_using_temporary_files(io.BytesIO(self.download_to_bytes(result.url)))
                with open(f"Cleaned_{i}.wav", "wb") as fp:
                    cleanedAudio.export(fp, format="wav")
                helper.logger.debug(f"Removed noise from {i}")
                finalAudio = cleanedAudio
            except requests.exceptions.ConnectTimeout:
                helper.logger.error("Unable to contact audo.ai API, using non-cleaned audio.")
                finalAudio = normalizedAudio
        else:
            finalAudio = normalizedAudio

        helper.logger.debug(f"Adding {i} to final queue")
        with self.durationLock:
            self.processedAudioQueue.put(finalAudio)
            self.totalDuration += finalAudio.duration_seconds
            cloneProgressSignal.emit(f"{self.totalDuration}")
            if self.totalDuration > requiredDuration and not self.dataComplete:
                helper.logger.debug(f"After {i} sound segments we have enough data to begin the clone.")
                self.dataComplete = True
                self.cloneQueue.put("dataComplete")
                self.processedAudioQueue.put(None)  #Mark the end of the processed audios



    @staticmethod
    def download_to_bytes(url):
        response = requests.get(url, stream=True)
        response.raise_for_status()
        bytesData = b""
        for chunk in response.iter_content(chunk_size=8192):
            bytesData += chunk
        return bytesData
