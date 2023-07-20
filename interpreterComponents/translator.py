import logging
import queue
import threading
from typing import Optional

import googletrans
import deepl
from PyQt6.QtCore import pyqtSignal

from utils import helper


class Translator:
    def __init__(self, deeplAPIKey:str, targetLang:str, tlQueue:queue.Queue, ttsQueue:queue.Queue):
        self.deepLTranslator:Optional[deepl.Translator] = None
        self.googleTranslator: googletrans.Translator = googletrans.Translator()
        self.interruptEvent = threading.Event()

        langName, langCode = targetLang.lower().split(" - ")

        #Edge cases for deepl.
        if langCode == "en":
            langCode = "en-us"

        if langCode == "pt":
            langCode = "pt-br"

        if deeplAPIKey is not None and deeplAPIKey != "":
            self.deepLTranslator = helper.get_deepl_translator(deeplAPIKey)

        self.targetLang = None

        # Let's check if the target language is supported by deepL.
        deepLSupported = False
        if self.deepLTranslator is not None:
            for language in self.deepLTranslator.get_target_languages():
                if language.code.lower() == langCode or language.name.lower() == langName:
                    deepLSupported = True
                    self.targetLang = {"code":language.code.lower(), "name":language.name.lower()}
                    break

        if not deepLSupported:
            self.deepLTranslator = None #No deepL support.
            for code, name in googletrans.LANGUAGES.items():
                if langCode.lower() == code.lower() or langName.lower() == name.lower():
                    self.targetLang = {"code": code.lower(), "name": name.lower()}
                    break

        if self.targetLang is None:
            raise ValueError("Neither google translate nor deepL support this language. Panic.")

        self.tlQueue = tlQueue
        self.ttsQueue = ttsQueue
    def main_loop(self, textReadySignal:pyqtSignal):
        while True:
            try:
                tlData = self.tlQueue.get(timeout=10)
            except queue.Empty:
                continue
            finally:
                if self.interruptEvent.is_set():
                    print("Translator exiting...")
                    return

            textToTL = tlData["text"]
            print(f"Translating from {tlData['lang']}...")
            sourceLang = tlData["lang"].lower()
            resultText = None
            if self.deepLTranslator is not None:
                #Assuming the language is a language name?
                isSupported = False
                for lang in self.deepLTranslator.get_source_languages():
                    if sourceLang in lang.name.lower(): #This should handle when/if the legacy "english" option is removed
                        isSupported = True
                        sourceLang = lang.code.upper()
                        break
                if isSupported:
                    #The source language is supported by deepL.
                    resultText = self.deepLTranslator.translate_text(textToTL, target_lang=self.targetLang["code"].upper(), source_lang=sourceLang.upper())

            if resultText is None:
                #DeepL was unable to translate it. Use googletrans.
                targetLang = self.targetLang["name"]
                if "(" in targetLang:
                    targetLang = targetLang[:targetLang.index("(")].strip()
                counter = 0
                while counter < 10:
                    try:
                        resultText = self.googleTranslator.translate(textToTL, dest=targetLang, src=sourceLang.lower())
                        break
                    except TypeError:
                        counter += 1
                if counter >= 10:
                    helper.logger.error("Unable to contact google translate after 10 retries. Giving up.")

            signalData = {
                "recognized": textToTL,
                "translated": resultText.text,
                "startTime": tlData["startTime"],
                "endTime": tlData["endTime"]
            }

            textReadySignal.emit(signalData)

            helper.logger.debug(f"Done translating.")
            self.ttsQueue.put(resultText.text)
