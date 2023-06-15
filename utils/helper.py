from __future__ import annotations
import json
import os
import platform
import re
from typing import Union

import googletrans
import httpcore
import sounddevice
import unicodedata
from elevenlabslib import ElevenLabsUser

#The following is a pre-baked list of translated languages.
langNamesPath = "utils/langnames.json"
tlCachePath = "utils/tlcache.json"
translator = googletrans.Translator()
with open(langNamesPath, "r") as fp:
    languages_translated = json.load(fp)

default_settings = {
    "voice_recognition_type": 0,
    "model_size": 2,
    "transcription_storage": 1,
    "ui_language": "System Language - syslang"
}

#Let's ensure that the tlCache exists and that we have a tlCache object.
if os.path.exists(tlCachePath):
    with open(tlCachePath, "r") as fp:
        tlCache = json.load(fp)
else:
    tlCache = dict()
    with open(tlCachePath, "w") as fp:
        json.dump(tlCache, fp, indent=4, ensure_ascii=False)
settings = dict()


def reload_settings():
    global settings
    if os.path.exists("config.json"):
        with open("config.json", "r") as fp:
            settings = json.load(fp)
    else:
        settings = default_settings
        with open("config.json", "w") as fp:
            json.dump(settings, fp, indent=4)

def dump_settings():
    with open("config.json", "w") as fp:
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
                    print(f"Couldn't find {name} ({code}), translating it...")
                    translated_name = translator.translate(name, dest=code).text
                    break
                except TypeError:
                    counter += 1
                except httpcore.TimeoutException:
                    print("Timeout error when trying to use google translate. Not going to translate.")
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
        with open(langNamesPath, "w") as fp:
            json.dump(languages_translated, fp, indent=4, ensure_ascii=False)

    sorted_langList = sorted(langList, key=lambda x: x.split(' - ')[0])
    for index, lang in enumerate(sorted_langList):
        if "english" in lang.lower():
            sorted_langList.pop(index)
            sorted_langList.insert(0, lang)
            break
    sysLangString = f"{translate_ui_text('System language',currentLang, cacheSkip=True)} - syslang"
    sorted_langList.insert(0, sysLangString)
    return sorted_langList

def tl_cache_prep(target_language):
    langCode = get_code_from_langstring(target_language)
    print(f"Preparing tl cache for {langCode}")
    #Bulk-translate all strings at once.

    # Extract all the keys (UI text to be translated)
    untranslated = [ui_text for ui_text in tlCache.keys() if langCode not in tlCache[ui_text]]
    if "Language Names" in untranslated:
        untranslated.remove("Language Names")
    if len(untranslated) == 0:
        print("No text to translate. Return.")
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
            print("Could not contact googletrans after 20 tries. Giving up.")
            return
        translations.extend(chunk_translations)

    #SANITY CHECK: Do we have the same amount of lines? If not, give up on the TL cache.
    if len(untranslated) != len(translations):
        return

    print("")
    # Update the JSON data with the translations
    for ui_text, translated_text in zip(untranslated, translations):
        if langCode not in tlCache[ui_text]:
            tlCache[ui_text][langCode] = translated_text

    # Save the updated data back to the JSON file
    with open(tlCachePath, 'w') as f:
        json.dump(tlCache, f, ensure_ascii=False, indent=4)

def translate_ui_text(text, language, cacheKey=None, cacheSkip=False):
    #Language is in the form "NativeName - LangCode"
    if text is None or text == "":
        return text

    langCode = get_code_from_langstring(language)

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
                print("Timeout error when trying to use google translate. Not going to translate.")
                break

        if translatedText is None:
            print("Failed to get translation. Not translating.")
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
        with open(tlCachePath, "w") as fp:
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
                        print(f"Device {device['name']} was skipped due to being marked inactive by CoreAudio.")
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
    for model in models:
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


    langStringTL = translate_ui_text(langString, languageToLocalizeIn, cacheKey="Language Names")
    langCode = languageToLocalizeIn.split(" - ")[1]

    # Split translated string back into individual language names and capitalize them if necessary
    langNamesTL = langStringTL.split("\n")
    if langCode not in ['ja', 'zh-cn', 'zh-tw'] and len(langCode) > 1:  # Add more if needed
        langNamesTL = [lang[0].upper() + lang[1:] for lang in langNamesTL]

    # Combine translated language names with language codes
    langList = [f"{langName} - {langCode}" for (langName, langCode) in zip(langNamesTL, (langCode for _, langCode in langPairs))]

    return langList