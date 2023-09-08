#Wrapper class for recognizer > translator > synthetizer
import gc
import logging
import queue
import threading
from typing import Optional

import keyring
from PyQt6.QtCore import QObject, pyqtSignal

from interpreterComponents.cloner import Cloner, ClonerParams
from interpreterComponents.detector import Detector, DetectorParams
from interpreterComponents.recognizer import Recognizer, RecognizerParams
from interpreterComponents.synthetizer import Synthesizer, SynthesizerParams
from interpreterComponents.translator import Translator, TranslatorParams
from utils import helper


class Interpreter(QObject):
    GIL = threading.Lock()
    textReadySignal = pyqtSignal(object)
    cloneProgressSignal = pyqtSignal(str)
    wRecognizer:Optional[Recognizer] = None
    wRecognizerThread:Optional[threading.Thread] = None

    @staticmethod
    def init_wrecognizer(params:RecognizerParams):
        if Interpreter.wRecognizer is None:
            if params.apiKey is not None or params.modelSize is not None:
                Interpreter.wRecognizer = Recognizer(params)
                Interpreter.wRecognizerThread = threading.Thread(target=Interpreter.wRecognizer.main_loop)

    #def __init__(self, audioInput: str, audioOutput: str, settings: dict, targetLang: str, voiceIDOrName: str, srSettings:tuple,createNewVoice: bool=False):
    def __init__(self, recognizerParams:RecognizerParams, detectorParams:DetectorParams, translatorParams:TranslatorParams, synthesizerParams:SynthesizerParams, clonerParams:ClonerParams=None):
        super().__init__()
        self.threads = list()
        self.interruptEvents = list()
        self._paused = threading.Event()
        self.ttsQueue = queue.Queue()
        self.tlQueue = queue.Queue()
        self.cloneQueue = queue.Queue() if clonerParams is not None else None

        self._init_detector(recognizerParams, detectorParams)
        self._init_translator(translatorParams)
        self._init_synthetizer(synthesizerParams, clonerParams)


    def _init_detector(self, recognizerParams:RecognizerParams, detectorParams:DetectorParams):
        #Initialize the recognizer...
        if recognizerParams.runLocal:
            helper.logger.debug(f"Using {recognizerParams.modelSize} for faster-whisper")

        with Interpreter.GIL:
            Interpreter.init_wrecognizer(recognizerParams)


        # Initialize the detector...
        #self.detector = Detector(inputDeviceName=audioInput,
        #                         srSettings=srSettings, tlQueue=self.tlQueue, cloneQueue=self.cloneQueue,
        #                         audioQueue=Interpreter.wRecognizer.audioQueue)
        self.detector = Detector(detectorParams, tlQueue=self.tlQueue, audioQueue=Interpreter.wRecognizer.audioQueue, cloneQueue=self.cloneQueue)

        self.interruptEvents.append(self.detector.interruptEvent)

    def _init_translator(self, translatorParams:TranslatorParams):
        self.translator = Translator(translatorParams, tlQueue=self.tlQueue, ttsQueue=self.ttsQueue)
        self.interruptEvents.append(self.translator.interruptEvent)

    def _init_synthetizer(self, synthesizerParams:SynthesizerParams, clonerParams:ClonerParams=None):
        if clonerParams is not None:
            self.__init_cloner(clonerParams)

        self.synthetizer = Synthesizer(synthesizerParams, ttsQueue=self.ttsQueue)

        self.interruptEvents.append(self.synthetizer.interruptEvent)

    def __init_cloner(self, clonerParams:ClonerParams):
        self.cloner = Cloner(clonerParams, cloneQueue=self.cloneQueue)
        self.interruptEvents.append(self.cloner.interruptEvent)


    def begin_interpretation(self):
        helper.log_usage_info("Before begin interpretation")
        self.threads.append(threading.Thread(target=self.detector.main_loop))
        self.threads.append(threading.Thread(target=self.translator.main_loop, args=(self.textReadySignal,)))
        self.threads.append(threading.Thread(target=self.synthetizer.main_loop))

        if self.cloneQueue is not None:
            self.threads.append(threading.Thread(target=self.wait_for_clone))

        for thread in self.threads:
            thread.start()

        if Interpreter.wRecognizerThread is not None and not Interpreter.wRecognizerThread.is_alive():
            Interpreter.wRecognizerThread.start()

        helper.log_usage_info("After begin interpretation")

    def set_interrupts(self):
        with Interpreter.GIL:
            if Interpreter.wRecognizer is not None:
                Interpreter.wRecognizer.interruptEvent.set()

        for event in self.interruptEvents:
            event.set()


    def stop_interpretation(self):
        with Interpreter.GIL:
            if Interpreter.wRecognizer is not None:
                if Interpreter.wRecognizerThread.is_alive():
                    Interpreter.wRecognizerThread.join()

                Interpreter.wRecognizer = None
                Interpreter.wRecognizerThread = None

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
