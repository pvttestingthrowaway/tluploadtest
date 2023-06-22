#Wrapper class for recognizer > translator > synthetizer
import queue
import threading

import keyring
from PyQt6.QtCore import QObject, pyqtSignal

from interpreterComponents.cloner import Cloner
from interpreterComponents.detector import Detector
from interpreterComponents.synthetizer import Synthesizer
from interpreterComponents.translator import Translator
from utils import helper

GIL = threading.Lock()
class Interpreter(QObject):
    textReadySignal = pyqtSignal(object)
    cloneProgressSignal = pyqtSignal(str)


    def __init__(self, audioInput: str, audioOutput: str, settings: dict, targetLang: str, voiceIDOrName: str, srSettings:tuple,createNewVoice: bool=False):
        super().__init__()
        self.threads = list()
        self.interruptEvents = list()
        self._paused = threading.Event()
        self.ttsQueue = queue.Queue()
        self.tlQueue = queue.Queue()
        self.cloneQueue = None
        self.cloner = None
        useLocal = settings["voice_recognition_type"] == 0
        openAIAPIKey = keyring.get_password("polyecho", "openai_api_key")
        deepLAPIKey = keyring.get_password("polyecho", "deepl_api_key")
        audoApiKey = keyring.get_password("polyecho", "audo_api_key")

        modelSizes = ["base", "small", "medium", "large-v2"]
        modelSize = modelSizes[settings["model_size"]]
        if useLocal:
            print(f"Using {modelSize} for faster-whisper")
        xiApiKey = keyring.get_password("polyecho", "elevenlabs_api_key")

        placeHolderVoiceID = settings["placeholder_ai_voice"]
        placeHolderVoiceID = placeHolderVoiceID[placeHolderVoiceID.index(" - ")+3:]

        if createNewVoice:
            voiceID = placeHolderVoiceID
            self.cloneQueue = queue.Queue()
            self.cloner = Cloner(cloneQueue=self.cloneQueue, xiApikey=xiApiKey, voiceName=voiceIDOrName,audoApiKey=audoApiKey)
        else:
            voiceID = voiceIDOrName[voiceIDOrName.index(" - ") + 3:]

        self.synthetizer = Synthesizer(apiKey=xiApiKey, outputDeviceName=audioOutput, ttsQueue=self.ttsQueue, voiceID=voiceID, isPlaceHolder=createNewVoice)

        self.detector = Detector(runLocal=useLocal, apiKey=openAIAPIKey, inputDeviceName=audioInput,
                                 srSettings=srSettings, modelSize=modelSize, tlQueue=self.tlQueue, cloneQueue=self.cloneQueue)

        self.translator = Translator(deeplAPIKey=deepLAPIKey, targetLang=targetLang, tlQueue=self.tlQueue, ttsQueue=self.ttsQueue)

        if self.detector.recognizerData is not None:
            self.interruptEvents.append(self.detector.recognizerData["event"])
            self.threads.append(self.detector.recognizerData["thread"])

        self.interruptEvents.append(self.detector.interruptEvent)
        self.interruptEvents.append(self.translator.interruptEvent)
        self.interruptEvents.append(self.synthetizer.interruptEvent)
        if self.cloneQueue is not None:
            self.interruptEvents.append(self.cloner.interruptEvent)

    def begin_interpretation(self):
        helper.print_usage_info("Before begin interpretation")
        self.threads.append(threading.Thread(target=self.detector.main_loop))
        self.threads.append(threading.Thread(target=self.translator.main_loop, args=(self.textReadySignal,)))
        self.threads.append(threading.Thread(target=self.synthetizer.main_loop))

        if self.cloneQueue is not None:
            self.threads.append(threading.Thread(target=self.wait_for_clone))

        for thread in self.threads:
            thread.start()
        helper.print_usage_info("After begin interpretation")
        print("Intepretation started.")

    def stop_interpretation(self):
        for event in self.interruptEvents:
            event.set()

        for thread in self.threads:
            thread.join()

    def wait_for_clone(self):
        newVoiceID = self.cloner.main_loop(self.cloneProgressSignal)
        if newVoiceID is None:
            return  #Exited before it could be completed.

        self.synthetizer.set_voice(newVoiceID)
        self.detector.cloneQueue = None
    #These two methods are different owing to the difference in pause behavior.
    @property
    def detector_paused(self):
        return not self.detector.isRunning.is_set()

    @detector_paused.setter
    def detector_paused(self, value):
        if value:
            self.detector.isRunning.clear()
        else:
            self.detector.isRunning.set()

    @property
    def synthetizer_paused(self):
        return not self.detector.isRunning.is_set()

    @synthetizer_paused.setter
    def synthetizer_paused(self, value):
        if value:
            self.synthetizer.isRunning.clear()
        else:
            self.synthetizer.isRunning.set()


    @property
    def paused(self):
        return self._paused.is_set()

    @paused.setter
    def paused(self, value):
        if value:
            self._paused.set()
        else:
            self._paused.clear()
