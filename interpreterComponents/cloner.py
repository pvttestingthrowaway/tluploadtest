import queue
import threading

import requests
import io

from PyQt6.QtCore import pyqtSignal
from elevenlabslib import ElevenLabsUser
from pydub import AudioSegment, effects
from audoai.noise_removal import NoiseRemovalClient
from queue import Queue

from speech_recognition import AudioData

requiredDuration = 180

class Cloner:
    def __init__(self, cloneQueue, xiApikey, voiceName, audoApiKey=None):
        self.cloneQueue = cloneQueue
        self.voiceName = voiceName
        self.user = ElevenLabsUser(xiApikey)
        self.noiseRemoval = None if audoApiKey is None else NoiseRemovalClient(api_key=audoApiKey)
        self.interruptEvent = threading.Event()
        self.processedAudio = list()
        self.totalDuration = 0

    def main_loop(self, cloneProgressSignal:pyqtSignal):
        while True:
            try:
                audioData:AudioData = self.cloneQueue.get(timeout=30)
            except queue.Empty:
                if self.interruptEvent.is_set():
                    print("Cloner main loop exiting...")
                    return None
                continue
            cleanedAudio:AudioSegment = self.clean_audio(audioData.get_wav_data())
            self.totalDuration += cleanedAudio.duration_seconds
            #TODO: Sync this with the label.
            cloneProgressSignal.emit(f"{self.totalDuration}")
            self.processedAudio.append(cleanedAudio)

            if self.totalDuration > requiredDuration:
                cloneProgressSignal.emit(f"PROCESSING")
                #We have enough audioData to create a clone.
                finalizedAudioBytes = list()
                finalizedAudio = AudioSegment.empty()
                silence = AudioSegment.silent(500)
                sizeLimit = 9*1024*1024
                for audio in self.processedAudio:
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
                    finalizedAudio.append(finalizedAudio)


                samplesDict = dict()
                for index,audioBytes in enumerate(finalizedAudioBytes):
                    samplesDict[f"{self.voiceName}_sample_{index}.mp3"] = audioBytes

                newVoiceID = self.user.clone_voice_bytes(self.voiceName, samplesDict).voiceID
                cloneProgressSignal.emit(f"COMPLETE")
                return newVoiceID

    def clean_audio(self, wavBytes:bytes) -> AudioSegment:
        audio = AudioSegment.from_file_using_temporary_files(io.BytesIO(wavBytes))
        audio = effects.normalize(audio)
        target_dBFS = -15
        normalizedAudio = audio.apply_gain(target_dBFS - audio.dBFS)

        if self.noiseRemoval is not None:
            mp3Bytes = io.BytesIO()
            #Turn into mp3 for smaller upload filesize
            normalizedAudio.export(mp3Bytes, format="mp3")
            mp3Bytes.seek(0)
            result = self.noiseRemoval.process(mp3Bytes)
            cleanedAudio = AudioSegment.from_file_using_temporary_files(io.BytesIO(self.download_to_bytes(result.url)))
            return cleanedAudio
        else:
            return normalizedAudio

    @staticmethod
    def download_to_bytes(url):
        response = requests.get(url, stream=True)
        response.raise_for_status()
        bytesData = b""
        for chunk in response.iter_content(chunk_size=8192):
            bytesData += chunk
        return bytesData
