from __future__ import annotations
import json
import os
import platform
import re
import webbrowser
from typing import Union, Optional

import deepl
import elevenlabslib
import googletrans
import httpcore
import psutil
import logging
import pynvml
import sounddevice
import unicodedata
import websocket
from PyQt6 import QtWidgets
from audoai.noise_removal import NoiseRemovalClient
from elevenlabslib import ElevenLabsUser


rootDir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

parentDir = os.path.dirname(rootDir)
if os.path.exists(os.path.join(parentDir, "install.py")):
    #We're running under the installer. Handle it accordingly.
    logsDir = os.path.join(parentDir, "logs")
else:
    #We're (probably) running under an IDE. Just put the logs in the rootDir.
    logsDir = os.path.join(rootDir, "logs")

# Create the logs directory if it doesn't exist
if not os.path.exists(logsDir):
    os.makedirs(logsDir)

cacheDir = os.path.join(rootDir, "cache")
resourcesDir = os.path.join(rootDir,"resources")
langNamesPath = os.path.join(resourcesDir, "langnames.json")
styleSheetPath = os.path.join(resourcesDir, "stylesheet.qss")
tlCachePath =  os.path.join(resourcesDir, "tlcache.json")

modelSizes = ["base", "small", "medium", "large-v2"]

translator = googletrans.Translator()
with open(langNamesPath, "r", encoding="utf8") as fp:
    languages_translated = json.load(fp)

#Logging setup...
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

debug_handler = logging.FileHandler(os.path.join(logsDir,'polyEcho-debug.log'))
error_handler = logging.FileHandler(os.path.join(logsDir,'polyEcho-error.log'))
debug_handler.setLevel(logging.DEBUG)
error_handler.setLevel(logging.ERROR)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
debug_handler.setFormatter(formatter)
error_handler.setFormatter(formatter)

logger.addHandler(debug_handler)
logger.addHandler(error_handler)

default_settings = {
    "voice_recognition_type": 0,
    "model_size": 2,
    "transcription_storage": 0,
    "ui_language": "System Language - syslang",
    "their_loudness_threshold": "250",
    "their_pause_time": "0.5"
}


colors_dict = {
    "primary_color":"#1A1D22",
    "secondary_color":"#282C34",
    "hover_color":"#596273",
    "text_color":"#FFFFFF",
    "toggle_color":"#4a708b",
    "green":"#3a7a3a",
    "yellow":"#faf20c",
    "red":"#7a3a3a"
}

#Let's ensure that the tlCache exists and that we have a tlCache object.
if os.path.exists(tlCachePath):
    with open(tlCachePath, "r", encoding="utf8") as fp:
        tlCache = json.load(fp)
else:
    tlCache = dict()
    with open(tlCachePath, "w", encoding="utf8") as fp:
        json.dump(tlCache, fp, indent=4, ensure_ascii=False)
settings = dict()

def get_stylesheet():
    with open(styleSheetPath, "r", encoding="utf8") as fp:
        styleSheet = fp.read()

    for colorKey, colorValue in colors_dict.items():
        styleSheet = styleSheet.replace("{" + colorKey + "}", colorValue)
    return styleSheet

def reload_settings():
    global settings
    if os.path.exists("config.json"):
        with open("config.json", "r", encoding="utf8") as fp:
            settings = json.load(fp)
    else:
        settings = default_settings
        with open("config.json", "w", encoding="utf8") as fp:
            json.dump(settings, fp, indent=4)

def dump_settings():
    with open("config.json", "w", encoding="utf8") as fp:
        json.dump(settings, fp, indent=4)

reload_settings()

def get_code_from_langstring(langString):
    langCode = langString.split(" - ")[1]

    if langCode.lower() == "syslang":
        if os.name == "nt":
            # windows-specific
            import ctypes
            windll = ctypes.windll.kernel32
            import locale
            langCode = locale.windows_locale[windll.GetUserDefaultUILanguage()]
            if "_" in langCode:
                langCode = langCode.split("_")[0]
        else:
            # macos or linux
            import locale
            langCode = locale.getdefaultlocale()[0].split("_")[0]

    return langCode

def get_googletrans_native_langnames(currentLang):
    langList = list()
    langCodesAdded = False
    for code, name in googletrans.LANGUAGES.items():
        if code in languages_translated:
            langList.append(f"{languages_translated[code]} - {code}")
        else:
            #It's not in the TL'd languages json. TL it and add it.
            counter = 0
            translated_name = None
            while counter < 10:
                try:
                    logger.debug(f"Couldn't find {name} ({code}), translating it...")
                    translated_name = translator.translate(name, dest=code).text
                    break
                except TypeError:
                    counter += 1
                except httpcore.TimeoutException:
                    logger.error("Timeout error when trying to use google translate. Not going to translate.")
                    break

            if translated_name is not None:
                first_char = translated_name[0]
                if unicodedata.category(first_char) == 'Ll':
                    translated_name = first_char.upper() + translated_name[1:]

            if translated_name is not None:
                langList.append(f"{translated_name} - {code}")
                langCodesAdded = True
                languages_translated[code] = translated_name
            else:
                langList.append(f"{name[0].upper() + name[1:]} - {code}")



    if langCodesAdded:
        with open(langNamesPath, "w", encoding="utf8") as fp:
            json.dump(languages_translated, fp, indent=4, ensure_ascii=False)

    sorted_langList = sorted(langList, key=lambda x: x.split(' - ')[0])
    for index, lang in enumerate(sorted_langList):
        if "english" in lang.lower():
            sorted_langList.pop(index)
            sorted_langList.insert(0, lang)
            break
    sysLangString = f"{translate_ui_text('System language',languageOverride=currentLang, cacheSkip=True)} - syslang"
    sorted_langList.insert(0, sysLangString)
    return sorted_langList

def tl_cache_prep(target_language):
    langCode = get_code_from_langstring(target_language)
    logger.debug(f"Preparing tl cache for {langCode}")
    #Bulk-translate all strings at once.

    # Extract all the keys (UI text to be translated)
    untranslated = [ui_text for ui_text in tlCache.keys() if langCode not in tlCache[ui_text]]
    if len(untranslated) == 0:
        logger.debug("No text to translate. Return.")
        return

    max_char_per_request = 2500
    chunks = []
    chunk = ""
    marker = "\n|\n"
    for ui_text in untranslated:
        # If adding the next text would exceed the limit, save the current chunk
        if len(chunk) + len(ui_text) + 1 > max_char_per_request:
            chunks.append(chunk)
            chunk = ui_text
        else:
            chunk = chunk + marker + ui_text if chunk else ui_text
        # Don't forget the last chunk
    if chunk:
        chunks.append(chunk)


    # Translate all text into the target language
    translations = list()
    for chunk in chunks:
        chunk_translations = None
        for i in range(20):
            try:
                chunk_translations:list = translator.translate(chunk, dest=langCode).text.split(marker)
                #Remove all the empty items
                while True:
                    try:
                        chunk_translations.remove("")
                    except ValueError:
                        break
                break
            except (TypeError, httpcore.TimeoutException):
                pass
        if chunk_translations is None:
            logger.error("Could not contact googletrans after 20 tries. Giving up.")
            return
        translations.extend(chunk_translations)

    #SANITY CHECK: Do we have the same amount of lines? If not, give up on the TL cache.
    if len(untranslated) != len(translations):
        return

    # Update the JSON data with the translations
    for ui_text, translated_text in zip(untranslated, translations):
        if langCode not in tlCache[ui_text]:
            tlCache[ui_text][langCode] = translated_text

    # Save the updated data back to the JSON file
    with open(tlCachePath, 'w', encoding="utf8") as f:
        json.dump(tlCache, f, ensure_ascii=False, indent=4)

def translate_ui_text(text, cacheKey=None, cacheSkip=False, languageOverride=None):
    #Language is in the form "NativeName - LangCode"
    if text is None or text == "":
        return text
    if languageOverride is not None:
        langCode = get_code_from_langstring(languageOverride)
    else:
        langCode = get_code_from_langstring(settings["ui_language"])

    cacheUpdated = False
    if cacheKey is None:
        cacheKey = text

    if cacheKey not in tlCache:
        tlCache[cacheKey] = dict()
        cacheUpdated = True

    if langCode not in tlCache[cacheKey] or cacheSkip:
        cacheUpdated = True

        counter = 0
        translatedText = None
        while counter < 10:
            try:
                if "en" in langCode.lower():
                    translatedText = text
                else:
                    translatedText = translator.translate(text, dest=langCode).text
                break
            except TypeError:
                counter += 1
            except httpcore.TimeoutException:
                logger.error("Timeout error when trying to use google translate. Not going to translate.")
                break

        if translatedText is None:
            logger.error("Failed to get translation. Not translating.")
            translatedText = text
            translatedText = translatedText[0].upper() + translatedText[1:]
        else:
            if not cacheSkip:
                tlCache[cacheKey][langCode] = translatedText
    else:
        translatedText = tlCache[cacheKey][langCode]

    if langCode not in ['ja', 'zh-cn', 'zh-tw']:  # Add more if needed
        translatedText = translatedText[0].upper() + translatedText[1:]

    translatedText = re.sub(r'deepl', 'DeepL', translatedText, flags=re.IGNORECASE)
    translatedText = translatedText.strip()

    if cacheUpdated and not cacheSkip:
        with open(tlCachePath, "w", encoding="utf8") as fp:
            json.dump(tlCache, fp, indent=4, ensure_ascii=False)


    return translatedText

def get_list_of_portaudio_devices(deviceType:str, includeVirtual=False) -> list[str]:
    """
    Returns a list containing all the names of portaudio devices of the specified type.
    """
    if deviceType != "output" and deviceType != "input":
        raise ValueError("Invalid audio device type.")
    hostAPIinfo = None

    if platform.system() == "Linux":
        for apiInfo in sounddevice.query_hostapis():
            if "ALSA" in apiInfo["name"]:
                hostAPIinfo = apiInfo
                break

    if hostAPIinfo is None:
        hostAPIinfo = sounddevice.query_hostapis(sounddevice.default.hostapi)

    deviceNames = list()
    activeDevices = None
    if platform.system() == "Windows":
        activeDevices = get_list_of_active_coreaudio_devices(deviceType)

    for deviceID in hostAPIinfo["devices"]:
        device = sounddevice.query_devices(deviceID)
        if device[f"max_{deviceType}_channels"] > 0:
            if platform.system() == "Linux" and not includeVirtual:
                if "(hw:" in device["name"]:
                    deviceNames.append(device["name"] + " - " + str(device["index"]))
            else:
                if activeDevices is not None:
                    deviceIsActive = False
                    for activeDevice in activeDevices:
                        if device["name"] in activeDevice.FriendlyName:
                            if "VB-Audio" not in activeDevice.FriendlyName or includeVirtual:
                                deviceNames.append(activeDevice.FriendlyName + " - " + str(device["index"]))
                            deviceIsActive = True
                            break
                    if not deviceIsActive:
                        logger.debug(f"Device {device['name']} was skipped due to being marked inactive by CoreAudio.")
                else:
                    if "VB-Audio" not in device["name"] or includeVirtual:
                        deviceNames.append(device["name"] + " - " + str(device["index"]))

    deviceNames.insert(0, "Default")
    return deviceNames

def get_list_of_active_coreaudio_devices(deviceType:str) -> list:
    if platform.system() != "Windows":
        raise NotImplementedError("This is only valid for windows.")

    import comtypes
    from pycaw.pycaw import AudioUtilities, IMMDeviceEnumerator, EDataFlow, DEVICE_STATE
    from pycaw.constants import CLSID_MMDeviceEnumerator

    if deviceType != "output" and deviceType != "input":
        raise ValueError("Invalid audio device type.")

    if deviceType == "output":
        EDataFlowValue = EDataFlow.eRender.value
    else:
        EDataFlowValue = EDataFlow.eCapture.value
    # Code to enumerate devices adapted from https://github.com/AndreMiras/pycaw/issues/50#issuecomment-981069603

    devices = list()
    deviceEnumerator = comtypes.CoCreateInstance(
        CLSID_MMDeviceEnumerator,
        IMMDeviceEnumerator,
        comtypes.CLSCTX_INPROC_SERVER)
    if deviceEnumerator is None:
        raise ValueError("Couldn't find any devices.")
    collection = deviceEnumerator.EnumAudioEndpoints(EDataFlowValue, DEVICE_STATE.ACTIVE.value)
    if collection is None:
        raise ValueError("Couldn't find any devices.")

    count = collection.GetCount()
    for i in range(count):
        dev = collection.Item(i)
        if dev is not None:
            if not ": None" in str(AudioUtilities.CreateDevice(dev)):
                devices.append(AudioUtilities.CreateDevice(dev))

    return devices

def get_portaudio_device_info_from_name(deviceName:str, deviceType:str):
    if deviceName.lower() == "default":
        device = sounddevice.query_devices(kind=deviceType.lower())
        return device
    deviceID = int(deviceName[deviceName.rfind(" - ") + 3:])
    deviceName = deviceName[:deviceName.rfind(" - ")]
    deviceInfo = sounddevice.query_devices(deviceID)
    if deviceInfo["name"].lower() not in deviceName.lower():
        raise RuntimeError("Device ID and Name mismatch! Device ordering must've changed.")

    return deviceInfo

def get_list_of_voices(user:ElevenLabsUser|None):
    if user is None:
        return []
    return  [f"{voice.initialName} - {voice.voiceID}" for voice in user.get_available_voices()]

def get_supported_languages(user:ElevenLabsUser|None):
    if user is None:
        return []
    models = user.get_available_models()
    nameList = [model["name"].lower() for model in models]
    v2Model = None

    for name in nameList:
        if "multilingual_v2" in name:
            v2Model = name

    for model in models:
        if v2Model is not None and model["name"].lower() == v2Model:
            # Found the multilingual v2 model
            return [f"{language['name']} - {language['language_id']}" for language in model["languages"]]

        if "multilingual" in model["name"].lower():
            #Found the multilingual model
            return [f"{language['name']} - {language['language_id']}" for language in model["languages"]]

    return []


def get_supported_languages_localized(user:ElevenLabsUser|None, languageToLocalizeIn:str):
    langList = get_supported_languages(user)
    if len(langList) == 0:
        return langList
    langPairs = [(language.split(" - ")[0], language.split(" - ")[1]) for language in langList]

    # Join language names with \n to prepare for translation
    langString = "\n".join(langName for langName, langCode in langPairs)


    langStringTL = translate_ui_text(langString, cacheKey="Language Names", languageOverride=languageToLocalizeIn, cacheSkip=True)
    langCode = languageToLocalizeIn.split(" - ")[1]

    # Split translated string back into individual language names and capitalize them if necessary
    langNamesTL = langStringTL.split("\n")
    if langCode not in ['ja', 'zh-cn', 'zh-tw'] and len(langCode) > 1:  # Add more if needed
        langNamesTL = [lang[0].upper() + lang[1:] for lang in langNamesTL]

    # Combine translated language names with language codes
    langList = [f"{langName} - {langCode}" for (langName, langCode) in zip(langNamesTL, (langCode for _, langCode in langPairs))]

    return langList

def get_virtual_devices() -> dict:
    devices = dict()
    devices["you"] = dict()
    devices["them"] = dict()
    for deviceType in ["input","output"]:
        for deviceName in get_list_of_portaudio_devices(deviceType, True):
            if "cable-a" in deviceName.lower():
                devices["you"][deviceType] = deviceName
            if "cable-b" in deviceName.lower():
                devices["them"][deviceType] = deviceName

    return devices

maxAPIRetries = 3
def get_xi_user(apiKey, exitOnFail=True) -> Optional[elevenlabslib.ElevenLabsUser]:
    errorMessage = ""
    for i in range(maxAPIRetries):
        try:
            user: elevenlabslib.ElevenLabsUser = elevenlabslib.ElevenLabsUser(apiKey)
            return user
        except ValueError:
            errorMessage = "Invalid API key!"
            break
        except AttributeError:
            errorMessage = "Could not connect to the Elevenlabs API. Please try again later."

    # We exhausted the tries without successfully getting the user.
    if exitOnFail:
        show_msgbox_and_exit(errorMessage)

    return None

def get_deepl_translator(apiKey, exitOnFail=True) -> Optional[deepl.Translator]:
    errorMessage = ""
    for i in range(maxAPIRetries):
        try:
            deeplTranslator = deepl.Translator(apiKey).set_app_info("polyecho", "1.0.0")
            deeplTranslator.get_usage()
            return deeplTranslator
        except (deepl.DeepLException, ValueError):
            errorMessage = "\nDeepL API error. API Key may be incorrect."

    # We exhausted the tries without successfully getting the user.
    if exitOnFail:
        show_msgbox_and_exit(errorMessage)

    return None

def get_audo_client(apiKey, exitOnFail=True) -> Optional[NoiseRemovalClient]:
    errorMessage = ""
    for i in range(maxAPIRetries):
        audoClient = NoiseRemovalClient(apiKey)
        try:
            socket = audoClient.connect_websocket("TestID")
            socket.close()
            return audoClient
        except websocket.WebSocketBadStatusException:
            errorMessage = "Audo API error. API Key may be incorrect, or it may be unreachable."

    # We exhausted the tries without successfully getting the user.
    if exitOnFail:
        show_msgbox_and_exit(errorMessage)
    return None


def find_model_bin(root_dir):
    for item in os.listdir(root_dir):
        item_path = os.path.join(root_dir, item)
        if os.path.isdir(item_path):
            if "model.bin" in os.listdir(item_path):
                return True  # "model.bin" found, return True
            else:
                # Recursively search in the sub-directory
                if find_model_bin(
                        item_path):  # If "model.bin" found in a sub-directory, return True
                    return True
    return False  # "model.bin" not found in any directories, return False

def show_msgbox_and_exit(text, url=None, urlBtnText=None, exitCode=1):
    logger.error(f"Requested exit with message {text}")
    msgBox = QtWidgets.QMessageBox()
    msgBox.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    msgBox.setText(translate_ui_text(text))
    if url is not None:
        open_site_button = msgBox.addButton(translate_ui_text(urlBtnText), QtWidgets.QMessageBox.ButtonRole.ActionRole)
    msgBox.addButton(QtWidgets.QMessageBox.StandardButton.Close)

    retval = msgBox.exec()

    if url is not None and msgBox.clickedButton() == open_site_button:
        webbrowser.open_new_tab(url)

    exit(exitCode)

def log_usage_info(codeID):
    logger.debug("===================RESOURCE USAGE STATS===================")
    logger.debug(codeID)
    try:
        from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo
        nvmlInit()
        h = nvmlDeviceGetHandleByIndex(0)
        info = nvmlDeviceGetMemoryInfo(h)
        logger.debug(f"VRAM usage: {round(info.used / pow(10, 9), 2)}GB")
    except pynvml.NVMLError:
        pass    #No NVIDIA GPU probably.

    process = psutil.Process(os.getpid())
    logger.debug(f"RAM usage: {round(process.memory_info().rss / pow(10, 9), 2)}GB")