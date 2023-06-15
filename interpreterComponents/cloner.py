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

requiredDuration = 180

class Cloner:
    def __init__(self, cloneQueue, xiApikey, voiceName, audoApiKey=None):
        self.cloneQueue = cloneQueue
        self.voiceName = voiceName
        self.user = ElevenLabsUser(xiApikey)
        self.noiseRemoval = None if audoApiKey is None else NoiseRemovalClient(api_key=audoApiKey)
        self.interruptEvent = threading.Event()
        self.processedAudioQueue = queue.Queue()
        self.totalDuration = 0
        self.durationLock = threading.Lock()
        self.dataComplete = False

    def main_loop(self, cloneProgressSignal:pyqtSignal):
        while True:
            try:
                audioData:Union[AudioData,str] = self.cloneQueue.get(timeout=5)
            except queue.Empty:
                if self.interruptEvent.is_set():
                    print("Cloner main loop exiting...")
                    return None
                continue
            print("Recieved audioSegment to clone.")

            if isinstance(audioData, AudioData):
                threading.Thread(target=self.clean_audio, args=(audioData.get_wav_data(), cloneProgressSignal)).start()
            else:
                print("We have enough audioData to create a clone.")
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
                    finalizedAudio.append(finalizedAudio)


                samplesDict = dict()
                for index,audioBytes in enumerate(finalizedAudioBytes):
                    samplesDict[f"{self.voiceName}_sample_{index}.mp3"] = audioBytes

                newVoiceID = self.user.clone_voice_bytes(self.voiceName, samplesDict).voiceID
                cloneProgressSignal.emit(f"COMPLETE")
                return newVoiceID

    def clean_audio(self, wavBytes:bytes, cloneProgressSignal:pyqtSignal):
        i = 0
        while os.path.exists(f"fileOriginal_{i}.wav"):
            i += 1

        with open(f"Original_{i}.wav", "wb") as fp:
            fp.write(wavBytes)
        print(f"Processing audio {i}.")
        audio = AudioSegment.from_file_using_temporary_files(io.BytesIO(wavBytes))
        audio = effects.normalize(audio)
        target_dBFS = -15
        normalizedAudio:AudioSegment = audio.apply_gain(target_dBFS - audio.dBFS)

        with open(f"Normalized_{i}.wav", "wb") as fp:
            normalizedAudio.export(fp, format="wav")

        print(f"Normalized audio {i}.")
        if self.noiseRemoval is not None:
            print(f"Removing noise from {i}")
            mp3Bytes = io.BytesIO()
            #Turn into mp3 for smaller upload filesize
            normalizedAudio.export(mp3Bytes, format="mp3")
            mp3Bytes.seek(0)
            result = self.noiseRemoval.process(mp3Bytes, input_extension="mp3", output_extension="mp3")
            cleanedAudio = AudioSegment.from_file_using_temporary_files(io.BytesIO(self.download_to_bytes(result.url)))
            with open(f"Cleaned_{i}.wav", "wb") as fp:
                cleanedAudio.export(fp, format="wav")
            print(f"Removed noise from {i}")
            finalAudio = cleanedAudio
        else:
            finalAudio = normalizedAudio

        print(f"Adding {i} to final queue")
        with self.durationLock:
            self.processedAudioQueue.put(finalAudio)
            self.totalDuration += finalAudio.duration_seconds
            cloneProgressSignal.emit(f"{round(self.totalDuration)}")
            if self.totalDuration > requiredDuration and not self.dataComplete:
                print(f"After {i} we have enough data to begin.")
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
