import copy
import os
import shutil
import sys
import threading
from typing import Optional

import deepl as deepl
import elevenlabslib
import keyring as keyring
import openai
import websocket
from PyQt6.QtGui import QIcon
from audoai.noise_removal import NoiseRemovalClient

from utils import helper
from utils.helper import settings, resourcesDir

from utils.customWidgets import *

class SpeechRecWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)

        self.myEnergyThreshold = LabeledInput(
            "My loudness threshold",
            configKey="my_loudness_threshold",
            data="250",
            info="This indicates how loud you have to be for your voice to be detected.\nShould be kept in the 200-300 range."
        )
        self.layout.addWidget(self.myEnergyThreshold, 0, 0)

        #self.dynamicLoudness = LocalizedCheckbox(configKey="dynamic_loudness",text="Dynamic loudness threshold")
        #self.layout.addWidget(self.dynamicLoudness, 0, 1)

        self.myPauseTime = LabeledInput(
            "My pause time (in seconds)",
            data="0.5",
            configKey="my_pause_time",
            info="This indicates how long you have to pause before a sentence is considered over."
        )
        self.layout.addWidget(self.myPauseTime, 1, 0)



        self.theirEnergyThreshold = LabeledInput(
            "Their loudness threshold",
            configKey="their_loudness_threshold",
            data="250"
        )
        self.layout.addWidget(self.theirEnergyThreshold, 0, 2)

        self.theirPauseTime = LabeledInput(
            "Their pause time (in seconds)",
            data="0.5",
            configKey="their_pause_time"
        )
        self.layout.addWidget(self.theirPauseTime, 1, 2)

        for i in range(3):
            self.layout.setColumnStretch(i, 1)

class LocalWidgets(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)

        self.VRAMlabel = LocalizedCenteredLabel(cacheSkip=True)
        self.update_memory_label()
        labels = ["1.5GB, 5GB", "2GB, 5GB", "3GB, 6GB", "4.5GB, 8GB"]
        self.slider = LabeledSlider(minimum=0, maximum=3,labels=labels, defaultPosition=2, configKey="model_size")
        self.layout.addWidget(LocalizedLabel("Fast"),0,0,1,1)
        self.layout.addWidget(self.slider, 0, 1, 2, 1)
        self.layout.addWidget(LocalizedLabel("Accurate"),0,2,1,1)

        self.layout.addWidget(self.VRAMlabel, 2, 0, 1, 3)  # add to the bottom

        #for i in range(3):
            #self.layout.setColumnStretch(i, 1)

    def update_memory_label(self):
        import torch
        if not torch.cuda.is_available():
            labelText = "CUDA support missing. Either you don't have an NVIDIA GPU, or it's not compatible with CUDA 11.\nUsing local mode is not recommended."
        else:
            from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo
            nvmlInit()
            h = nvmlDeviceGetHandleByIndex(0)
            info = nvmlDeviceGetMemoryInfo(h)
            labelText = f"You currently have {round(info.free / pow(10, 9), 2)}GB of VRAM available out of {round(info.total / pow(10, 9), 2)}GB."

        self.VRAMlabel.setText(labelText)
        self.layout.removeWidget(self.VRAMlabel)
        self.layout.addWidget(self.VRAMlabel, 2, 0, 1, 3)  # add to the bottom

class WhisperWidgets(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)
        for i in range(3):
            self.layout.setColumnStretch(i, 1)

        self.api_key = LabeledInput(
            "OpenAI API Key",
            configKey="openai_api_key",
            protected=True
        )
        self.layout.addWidget(self.api_key, 0, 1, 1, 1)
        # Set empty stretchable spacers in the first and third columns
        self.layout.setColumnStretch(0, 1)
        self.layout.setColumnStretch(2, 1)


#Note: This class is entirely unused. I was thinking of implementing azure support (like I did for Echo-XI) but 5 hours of speech rec (the free amount per month) cost just 2$ on Whisper.
#In short, not worth the dev time, given it's by far the most complex one to implement.
class AzureWidgets(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)
        for i in range(3):
            self.layout.setColumnStretch(i, 1)

        self.speechKey = LabeledInput(
            "Speech Key",
            protected=True,
            configKey="speech_key"
        )
        self.layout.addWidget(self.speechKey, 0, 0)

        self.serviceRegion = LabeledInput(
            "Service Region",
            configKey="service_region"
        )
        self.layout.addWidget(self.serviceRegion, 0, 2)

        self.centralLabel = LocalizedCenteredLabel("Languages to recognize")
        configKey = "languages_to_recognize"
        self.list_selection = TwoListSelection(configKey)
        self.list_selection.addAvailableItems(["item-{}".format(i) for i in range(50)])
        self.list_selection.setMinimumHeight(250)


        if configKey in settings:
            self.list_selection.addSelectedItems(settings[configKey])

        self.layout.addWidget(self.centralLabel, 1, 1, 1, 1)
        self.layout.addWidget(self.list_selection, 2, 0, 4, 3)

class ConfigDialog(LocalizedDialog):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Settings")
        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        user = None
        errorMessage = None
        for i in range(3):
            try:
                user: Optional[elevenlabslib.ElevenLabsUser] = elevenlabslib.ElevenLabsUser(apiKey)
            except ValueError:
                break
            except AttributeError:
                errorMessage = "Could not connect to the Elevenlabs API. Please try again later."

        if errorMessage is not None:
            helper.show_msgbox_and_exit(errorMessage)

        currentRow = 0


        self.root_layout = QtWidgets.QGridLayout(self)


        self.layout = QtWidgets.QGridLayout()
        self.input_device = LabeledInput(
            "Audio input device",
            configKey = "audio_input_device",
            data=helper.get_list_of_portaudio_devices("input"),
            info=f"dummy"
        )
        virtualDevices = helper.get_virtual_devices()
        inputInfo = helper.translate_ui_text("This is the microphone you will be speaking into.<br>")   #have to use BR due to pyqt quirk.
        virtualInput = virtualDevices['you']['input']
        virtualInput = virtualInput[:virtualInput.index(" - ")]
        inputInfo += helper.translate_ui_text("Please set the input device in your chat app to") + f": {virtualInput}"
        self.input_device.info_button.info = inputInfo
        self.layout.addWidget(self.input_device, currentRow, 0)

        self.output_device = LabeledInput(
            "Audio output device",
            configKey="audio_output_device",
            data = helper.get_list_of_portaudio_devices("output"),
            info="This is the device you will hear audio from."
        )
        self.layout.addWidget(self.output_device, currentRow, 2)

        currentRow += 1

        input_label = LocalizedCenteredLabel("Virtual Input Device")
        output_label = LocalizedCenteredLabel("Virtual Output Device")
        self.layout.addWidget(input_label, currentRow, 0)
        self.layout.addWidget(output_label, currentRow, 2)

        currentRow += 1
        self.virtual_input = CenteredLabel(f'{virtualDevices["you"]["input"][:virtualDevices["you"]["input"].index(" - ")]}\n')
        self.virtual_output = CenteredLabel(f'{virtualDevices["them"]["output"][:virtualDevices["them"]["output"].index(" - ")]}\n')
        self.layout.addWidget(self.virtual_input, currentRow, 0)
        self.layout.addWidget(self.virtual_output, currentRow, 2)

        currentRow += 1

        hline = QtWidgets.QFrame()
        hline.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        hline.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.layout.addWidget(hline, currentRow, 0, 1, 3)

        currentRow += 1

        self.elevenlabs_api_key = LabeledInput(
            "ElevenLabs API Key",
            configKey="elevenlabs_api_key",
            info="You can find your API Key under your Profile, on the website.",
            protected=True
        )

        self.layout.addWidget(self.elevenlabs_api_key, currentRow, 0)

        currentRow += 1

        self.your_ai_voice = LabeledInput(
            "Your TTS Voice",
            configKey="your_ai_voice",
            data=helper.get_list_of_voices(user),
            info="This is the TTS voice that will be used to speak your translated messages."
        )
        self.layout.addWidget(self.your_ai_voice, currentRow, 0)

        self.placeholder_ai_voice = LabeledInput(
            "Placeholder TTS Voice",
            configKey="placeholder_ai_voice",
            data=helper.get_list_of_voices(user),
            info="This is the voice that will be used as a placeholder while copying the other user's actual voice."
        )
        self.layout.addWidget(self.placeholder_ai_voice, currentRow, 2)

        currentRow += 1

        hline = QtWidgets.QFrame()
        hline.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        hline.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.layout.addWidget(hline, currentRow, 0, 1, 3)

        currentRow += 1

        self.deepl_api_key = LabeledInput(
            "DeepL API Key",
            configKey="deepl_api_key",
            protected=True
        )
        self.layout.addWidget(self.deepl_api_key, currentRow, 2)

        self.deepl_toggle = ToggleButton(
            "DeepL Translation",
            ["Enabled", "Disabled"],
            [lambda: self.deepl_toggle_visibility(True), lambda: self.deepl_toggle_visibility(False)],
            info="Optional, providers better translation.\nIf a language is not supported by DeepL (or an API key is not provided) Google Translate will be used instead.",
            configKey="deepl_enabled"
        )
        self.layout.addWidget(self.deepl_toggle, currentRow, 0)
        self.deepl_api_key.setVisible(self.deepl_toggle.get_value() == 0)

        currentRow += 1

        self.audo_api_key = LabeledInput(
            "Audo API Key",
            configKey="audo_api_key",
            protected=True
        )
        self.layout.addWidget(self.audo_api_key, currentRow, 2)

        self.audo_toggle = ToggleButton(
            "Audo.ai enhancement",
            ["Enabled", "Disabled"],
            [lambda: self.audo_toggle_visibility(True), lambda: self.audo_toggle_visibility(False)],
            info="Optional. Enhances the audio when imitating the other user's voice, resulting in a higher quality copy.",
            configKey="audo_enabled"
        )
        self.layout.addWidget(self.audo_toggle, currentRow, 0)
        self.audo_api_key.setVisible(self.audo_toggle.get_value() == 0)

        currentRow += 1

        self.transcript_save_location = LabeledInput(
            "Transcript save location",
            configKey="transcript_save_location",
            info="This is where transcripts will be saved.",
            infoIsDir=True
        )
        self.layout.addWidget(self.transcript_save_location, currentRow, 2)


        self.transcript_toggle = ToggleButton(
            "Transcription storage",
            ["Enabled", "Disabled"],
            [lambda: self.transcript_toggle_visibility(True), lambda: self.transcript_toggle_visibility(False)],
            info="If enabled, PolyEcho will save a .srt transcript of all audio (both the recognized and translated text) to the specified directory.",
            configKey="transcription_storage"
        )
        self.layout.addWidget(self.transcript_toggle, currentRow, 0)

        self.transcript_save_location.setVisible(self.transcript_toggle.get_value() == 0)



        self.speechRecWidgets = SpeechRecWidget()
        self.localWhisperWidgets = LocalWidgets()
        #self.azureWidgets = AzureWidgets()
        self.whisperAPIWidgets = WhisperWidgets()


        self.whisperAPIWidgets.setVisible(False)

        #self.layout.addWidget(self.azureWidgets, 6, 0, 4, 3)
        #self.azureWidgets.setVisible(False)



        #self.online_provider = ToggleButton(
        #    "Speech Recognition Provider",
        #    ["Whisper", "Azure"],
        #    [self.on_whisper, self.on_azure],
        #    "Data about providers."
        #)

        self.voice_recognition_type = ToggleButton(
            "Voice recognition type",
            ["Local", "Online"],
            [self.on_local, self.on_online],
            info="This is the type of voice recognition.<br>Local runs on your machine, is free, and is the fastest in terms of latency, but the speed depends on your GPU.<br>Online utilizes OpenAI's Whisper API. It has higher latency, but will run on any computer.",
            configKey="voice_recognition_type"
        )

        currentRow += 1

        self.layout.addWidget(self.voice_recognition_type, currentRow, 1)
        #self.layout.addWidget(self.online_provider, 5, 1)

        currentRow += 1

        self.layout.addWidget(self.whisperAPIWidgets, currentRow, 0, 4, 3)
        self.layout.addWidget(self.localWhisperWidgets, currentRow, 0, 4, 3)

        currentRow += 4






        # Save and Cancel buttons
        buttonLayout = QtWidgets.QHBoxLayout()

        saveButton = QtWidgets.QPushButton(helper.translate_ui_text("Save"))
        saveButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        saveButton.setMinimumSize(30, 25)  # adjust the size as per your need
        saveButton.clicked.connect(self.save_clicked)
        buttonLayout.addWidget(saveButton)

        cancelButton = QtWidgets.QPushButton(helper.translate_ui_text("Cancel"))
        cancelButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        cancelButton.setMinimumSize(30, 25)  # adjust the size as per your need
        cancelButton.clicked.connect(self.cancel_clicked)
        buttonLayout.addWidget(cancelButton)
        wrapperLayout = QtWidgets.QVBoxLayout()
        wrapperLayout.addStretch()
        wrapperLayout.addLayout(buttonLayout)
        # add the button layout to the grid layout

        self.root_layout.addLayout(wrapperLayout, currentRow, 2)

        self.ui_language = LabeledInput(
            "Program Language",
            configKey="ui_language",
            data=helper.get_googletrans_native_langnames(settings["ui_language"])
        )

        self.root_layout.addWidget(self.ui_language, currentRow, 0, 1, 1)



        for i in range(3):
            self.layout.setColumnStretch(i, 1)
            self.root_layout.setColumnStretch(i, 1)

        for i in range(currentRow+1):
            self.layout.setRowStretch(i, 1)
            self.root_layout.setRowStretch(i, 1)

        self.settings_widget = QtWidgets.QWidget()
        self.settings_widget.setLayout(self.layout)
        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)  # Make the scroll area resizable
        self.scroll_area.setWidget(self.settings_widget)

        #With scroll
        self.root_layout.addWidget(self.scroll_area, 0, 0, currentRow, 3)
        #Without scroll
        #self.root_layout.addWidget(self.settings_widget, 0, 0, currentRow - 1, 3)
        self.setLayout(self.root_layout)  # Set root_layout as the layout for the main window (ConfigDialog)
        self.fix_size()


    def fix_size(self):
        # Get screen size
        screen = QtWidgets.QApplication.primaryScreen()
        self.adjustSize()

        if not hasattr(self, "settings_widget"):
            return  #Whoops, too early.

        # Now get the sizeHint of the settings_widget and compare it with the screen size

        recommended_size = self.settings_widget.sizeHint()
        screen_size = screen.availableGeometry()
        screen_size = QtCore.QSize(int(screen_size.width() * 8 / 10), int(screen_size.height() * 8 / 10))

        # Calculate the size to set (accounting for the scroll bars)
        size_to_set = QtCore.QSize(
            min(recommended_size.width() + self.scroll_area.verticalScrollBar().width() * 3, screen_size.width()),
            min(recommended_size.height() + self.scroll_area.horizontalScrollBar().height(), screen_size.height())
        )

        # Set the size of the dialog
        self.resize(size_to_set)

    def iterate_widgets(self,layout):
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget is not None:
                yield widget
                if isinstance(widget, QtWidgets.QWidget):
                    if callable(widget.layout):
                        child_layout = widget.layout()
                    else:
                        child_layout = widget.layout
                    if child_layout is not None:
                        yield from self.iterate_widgets(child_layout)
            else:
                child_layout = layout.itemAt(i).layout()
                if child_layout is not None:
                    yield from self.iterate_widgets(child_layout)

    def save_clicked(self):
        errorMessage = ""
        languageChanged = False
        if settings["ui_language"] != self.ui_language.get_value():
            languageChanged = True
            tlCachingThread = threading.Thread(target=helper.tl_cache_prep, args=(self.ui_language.get_value(),))
            tlCachingThread.start()

        recognitionModeChanged = settings["voice_recognition_type"] != self.voice_recognition_type.get_value()
        newSettings = copy.deepcopy(settings)
        for widget in self.iterate_widgets(self.layout):
            if hasattr(widget, 'configKey'):
                #Read and save the config data.
                configKey = widget.configKey
                value = widget.get_value()

                #Now we check the constraints depending on the API key.
                if configKey == "elevenlabs_api_key":
                    if keyring.get_password("polyecho","elevenlabs_api_key") != value:
                        user = helper.get_xi_user(apiKey=value, exitOnFail=False)
                        if user is None:
                            errorMessage += "\nElevenLabs API error. API Key may be incorrect."
                        elif not user.get_voice_clone_available():
                            msgBox = QtWidgets.QMessageBox()
                            msgBox.setText(helper.translate_ui_text("Your ElevenLabs subscription does not support voice cloning. \nSome features won't be available."))
                            msgBox.exec()


                if configKey == "openai_api_key":
                    if self.voice_recognition_type.get_value() == 1:
                        if recognitionModeChanged or keyring.get_password("polyecho","openai_api_key") != value:
                            openai.api_key = value
                            try:
                                openai.Model.list()
                            except openai.error.AuthenticationError:
                                errorMessage += "\nOpenAI API error. API Key may be incorrect."

                if configKey == "model_size" and self.voice_recognition_type.get_value() == 0:
                    modelSize = helper.modelSizes[value]
                    modelDir = os.path.join(helper.cacheDir, "faster-whisper", "models--guillaumekln--faster-whisper-" + modelSize)
                    modelFound = False

                    if os.path.exists(modelDir):
                        modelFound = helper.find_model_bin(modelDir)
                        if not modelFound:
                            #The folder exists, but we were unable to find the model. Must've been incomplete. Redo.
                            shutil.rmtree(modelDir)

                    if not modelFound:
                        ModelDownloadDialog("Downloading model...", modelSize).exec()

                if configKey == "deepl_api_key" and self.deepl_toggle.get_value() == 0:
                    if keyring.get_password("polyecho","deepl_api_key") != value:
                        deeplTranslator = helper.get_deepl_translator(value, exitOnFail=False)
                        if deeplTranslator is None:
                            errorMessage += "\nDeepL API error. API Key may be incorrect."

                if configKey == "audo_api_key" and self.audo_toggle.get_value() == 0:
                    if keyring.get_password("polyecho", "audo_api_key") != value:
                        audoClient = helper.get_audo_client(value, exitOnFail=False)
                        if audoClient is None:
                            errorMessage += "\nAudo API error. API Key may be incorrect."

                if configKey == "transcript_save_location":
                    if self.transcript_toggle.get_value() == 0:
                        if value is None or not os.path.isdir(value):
                            errorMessage += "\nSpecified transcript save location is not a valid directory."

                if "_loudness_threshold" in configKey:
                    try:
                        int(value)
                    except ValueError:
                        errorMessage += f"\n{configKey.replace('_loudness_threshold','')} loudness threshold must be a number"

                if "_pause_time" in configKey:
                    try:
                        float(value)
                    except ValueError:
                        errorMessage += f"\n{configKey.replace('_pause_time','')} pause time must be a number"

                useKeyring = hasattr(widget,"protected") and widget.protected

                if useKeyring:
                    configKey = "keyring_"+configKey

                if value is not None:
                    newSettings[configKey] = value



        if languageChanged:
            tlCachingThread.join()
        if errorMessage != "":
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText(helper.translate_ui_text(errorMessage))
            msgBox.exec()
            return
        else:
            keysToPop = list()
            for key, value in newSettings.items():
                if "keyring_" in key:
                    keyringKey = key[len("keyring_"):]
                    keyring.set_password("polyecho", keyringKey, value)
                    keysToPop.append(key)
            for key in keysToPop:
                newSettings.pop(key)
            for key, value in newSettings.items():
                settings[key] = value
            helper.dump_settings()
            self.close()

    def cancel_clicked(self):
        self.close()
    def transcript_toggle_visibility(self, visible):
        self.transcript_save_location.setVisible(visible)

    def audo_toggle_visibility(self, visible):
        self.audo_api_key.setVisible(visible)

    def deepl_toggle_visibility(self, visible):
        self.deepl_api_key.setVisible(visible)

    def on_local(self):
        self.localWhisperWidgets.setVisible(True)
        self.localWhisperWidgets.update_memory_label()
        #self.online_provider.setVisible(False)
        #self.azureWidgets.setVisible(False)
        self.whisperAPIWidgets.setVisible(False)
        self.localWhisperWidgets.layout.addWidget(self.speechRecWidgets, 3, 0, 2, 3)
        self.fix_size()

    def on_online(self):
        #self.online_provider.setVisible(True)
        self.localWhisperWidgets.setVisible(False)
        #self.adjustSize()

        #if self.online_provider.get_selected_button() == 0:
        self.on_whisper()
        #else:
        #    self.on_azure()
        self.fix_size()

    def on_azure(self):
        self.whisperAPIWidgets.setVisible(False)
        #self.azureWidgets.setVisible(True)

    def on_whisper(self):
        #self.azureWidgets.setVisible(False)
        self.whisperAPIWidgets.setVisible(True)
        self.whisperAPIWidgets.layout.addWidget(self.speechRecWidgets, 3, 0, 2, 3)
        self.adjustSize()


def main():
    app = QtWidgets.QApplication([])
    app.setWindowIcon(QIcon(os.path.join(helper.resourcesDir,'icon.ico')))

    dialog = ConfigDialog()
    dialog.show()

    app.exec()

if __name__ == "__main__":
    if os.name == "nt":
        import ctypes
        myappid = u'lugia19.polyecho'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    main()
