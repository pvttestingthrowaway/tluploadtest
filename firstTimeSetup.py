import datetime
import platform
import queue
import threading

from PyQt6 import QtGui

from configWindow import *
from interpreterComponents.detector import Detector


class SetupDialog(LocalizedDialog):
    def __init__(self, prompt):
        super().__init__()
        self.setWindowTitle("First time setup")
        self.gridLayout = QtWidgets.QGridLayout(self)
        self.promptLabel = LocalizedCenteredLabel(prompt, wordWrap=True)
        self.gridLayout.addWidget(self.promptLabel, 0, 0, 1, 3)
        self.saveExit = False

        self.nextButton = QtWidgets.QPushButton(helper.translate_ui_text("Next"))
        self.nextButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        self.nextButton.setMinimumSize(50, 25)
        self.nextButton.clicked.connect(self.save_clicked)

        # Create a QHBoxLayout, add a spacer and the nextButton to it
        hboxLayout = QtWidgets.QHBoxLayout()
        spacerItem = QtWidgets.QSpacerItem(20, 25, QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Minimum)
        hboxLayout.addItem(spacerItem)  # Add the spacer to the QHBoxLayout
        hboxLayout.addWidget(self.nextButton)  # Add the nextButton to the QHBoxLayout

        # Now add the new layout to the main gridLayout
        self.gridLayout.addLayout(hboxLayout, 99, 0, 1, 3)  # Span the QHBoxLayout across all 3 columns

    #This is just an edited version of configWindow's save_clicked method.
    def iterate_widgets(self, layout):
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
        self.saveExit = True
        if self.check_settings():
            self.close()


    def check_settings(self):
        errorMessage = ""

        newSettings = copy.deepcopy(settings)
        for widget in self.iterate_widgets(self.gridLayout):
            if hasattr(widget, 'configKey') and widget.isVisible():
                # Read and save the config data ONLY if the widget is visible (easier check for ToggleButtons).
                configKey = widget.configKey
                value = widget.get_value()

                if configKey == "ui_language" and settings["ui_language"] != value:
                    helper.tl_cache_prep(value)

                # Now we check the constraints depending on the API key.
                if configKey == "elevenlabs_api_key":
                    user = helper.get_xi_user(value, exitOnFail=False)
                    if user is None:
                        errorMessage += "\nElevenLabs API error. API Key may be incorrect."
                    elif not user.get_voice_clone_available():
                        msgBox = QtWidgets.QMessageBox()
                        msgBox.setText(helper.translate_ui_text("Your ElevenLabs subscription does not support voice cloning. \nSome features won't be available."))
                        msgBox.exec()

                if configKey == "openai_api_key" and hasattr(self, 'voice_recognition_type') and self.voice_recognition_type.get_value() == 1:
                    openai.api_key = value
                    try:
                        openai.Model.list()
                    except openai.error.AuthenticationError:
                        errorMessage += "\nOpenAI API error. API Key may be incorrect."

                if configKey == "model_size" and hasattr(self, 'voice_recognition_type') and self.voice_recognition_type.get_value() == 0:
                    modelSize = helper.modelSizes[value]
                    modelDir = os.path.join(helper.cacheDir, "faster-whisper",
                                            "models--guillaumekln--faster-whisper-" + modelSize)
                    modelFound = False

                    if os.path.exists(modelDir):
                        modelFound = helper.find_model_bin(modelDir)
                        if not modelFound:
                            # The folder exists, but we were unable to find the model. Must've been incomplete. Redo.
                            shutil.rmtree(modelDir)

                    if not modelFound:
                        ModelDownloadDialog("Downloading model...", modelSize).exec()

                if configKey == "deepl_api_key" and hasattr(self, 'deepl_toggle') and self.deepl_toggle.get_value() == 0:
                    deeplTranslator = helper.get_deepl_translator(value, exitOnFail=False)
                    if deeplTranslator is None:
                        errorMessage += "\nDeepL API error. API Key may be incorrect."

                if configKey == "audo_api_key" and hasattr(self, 'audo_toggle') and self.audo_toggle.get_value() == 0:
                    audoClient = helper.get_audo_client(value, exitOnFail=False)
                    if audoClient is None:
                        errorMessage += "\nAudo API error. API Key may be incorrect."

                if configKey == "transcript_save_location" and hasattr(self, 'transcript_toggle') and self.transcript_toggle.get_value() == 0:
                    if value is None or not os.path.isdir(value):
                        errorMessage += "\nSpecified transcript save location is not a valid directory."

                if "_loudness_threshold" in configKey:
                    try:
                        int(value)
                    except ValueError:
                        errorMessage += f"\n{configKey.replace('_loudness_threshold', '')} loudness threshold must be a number"

                if "_pause_time" in configKey:
                    try:
                        float(value)
                    except ValueError:
                        errorMessage += f"\n{configKey.replace('_pause_time', '')} pause time must be a number"

                useKeyring = hasattr(widget, "protected") and widget.protected

                if useKeyring:
                    configKey = "keyring_" + configKey

                if value is not None:
                    newSettings[configKey] = value


        if errorMessage != "":
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText(helper.translate_ui_text(errorMessage))
            msgBox.exec()
            return False
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
            return True

    def closeEvent(self, event):
        if self.saveExit:
            if self.check_settings():
                event.accept()
            else:
                event.ignore()
        else:
            reply = QtWidgets.QMessageBox.question(
                self,
                helper.translate_ui_text('Confirmation'),
                helper.translate_ui_text('Are you sure you want to quit?'),
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
            )

            if reply == QtWidgets.QMessageBox.StandardButton.Yes:
                exit()
            else:
                event.ignore()

class LanguageInput(SetupDialog):
    def __init__(self):
        super().__init__("Please choose the language to use for the application.\n NOTE: Any language other than English will be translated via Google Translate.")

        self.ui_language = LabeledInput(
            "GUI Language",
            configKey="ui_language",
            data=helper.get_googletrans_native_langnames(settings["ui_language"])
        )

        self.gridLayout.addWidget(self.ui_language, 1, 0, 1, 3)

class AudioDeviceInput(SetupDialog):
    def __init__(self):
        super().__init__("Please choose the input and output audio devices to use.")

        self.input_device = LabeledInput(
            "Audio input device",
            configKey="audio_input_device",
            data=helper.get_list_of_portaudio_devices("input")
        )
        self.gridLayout.addWidget(self.input_device, 1, 0)

        self.output_device = LabeledInput(
            "Audio output device",
            configKey="audio_output_device",
            data=helper.get_list_of_portaudio_devices("output")
        )
        self.gridLayout.addWidget(self.output_device, 1, 2)

class VirtualInputOutput(SetupDialog):
    def __init__(self):
        super().__init__("Please set the following devices as microphone and speakers\nin the chat program you'd like to use (eg. Zoom, Discord).")

        warning = LocalizedCenteredLabel("WARNING: In order to use your chosen program\nwithout PolyEcho, you will need to change them.")
        self.gridLayout.addWidget(warning, 1, 1)

        input_label = LocalizedCenteredLabel("Input device")
        output_label = LocalizedCenteredLabel("Output device")
        self.gridLayout.addWidget(input_label, 2, 0)
        self.gridLayout.addWidget(output_label, 2, 2)

        virtualDevices = helper.get_virtual_devices()
        try:
            self.virtual_input = CenteredLabel(virtualDevices["you"]["input"][:virtualDevices["you"]["input"].index(" - ")])
            self.virtual_output = CenteredLabel(virtualDevices["them"]["output"][:virtualDevices["them"]["output"].index(" - ")])
            self.gridLayout.addWidget(self.virtual_input, 3, 0)
            self.gridLayout.addWidget(self.virtual_output, 3, 2)
        except KeyError:
            currentOS = platform.system()
            if currentOS == 'Windows':
                errorText = "Could not detect VB-Cable devices. Please make sure VB-Cable A+B is installed."
                url = "https://shop.vb-audio.com/en/win-apps/12-vb-cable-ab.html?SubmitCurrency=1&id_currency=1"
                urlBtnText = "Buy VB-Cable A+B"
            elif currentOS == 'Darwin':
                errorText = "Could not detect VB-Cable devices. Please make sure VB-Cable A+B is installed."
                url = "https://shop.vb-audio.com/en/mac-apps/30-vb-cable-ab-mac.html?SubmitCurrency=1&id_currency=1"
                urlBtnText = "Buy VB-Cable A+B"
            else:
                errorText = "Could not detect virtual audio devices. Please make sure you have followed the setup guide."
                #TODO: Fill this in.
                url = ""
                urlBtnText = "Open setup guide"
            helper.show_msgbox_and_exit(errorText, url=url, urlBtnText=urlBtnText)



class ElevenLabsInput(SetupDialog):
    def __init__(self):
        super().__init__("Please input your ElevenLabs API Key.\nIt can be found under Profile, on elevenlabs.io")

        self.elevenlabs_api_key = LabeledInput(
            "ElevenLabs API Key",
            configKey="elevenlabs_api_key",
            protected=True
        )

        self.gridLayout.addWidget(self.elevenlabs_api_key, 1, 0, 1, 3)

class VoiceInput(SetupDialog):
    def __init__(self):
        super().__init__("Please choose your AI voice and the placeholder voice.")

        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        user = helper.get_xi_user(apiKey)

        self.your_ai_voice = LabeledInput(
            "Your AI Voice",
            configKey="your_ai_voice",
            data=helper.get_list_of_voices(user),
            info="This is the voice that will be used for your translated speech."
        )
        self.gridLayout.addWidget(self.your_ai_voice, 1, 0)

        self.placeholder_ai_voice = LabeledInput(
            "Placeholder AI Voice",
            configKey="placeholder_ai_voice",
            data=helper.get_list_of_voices(user),
            info="This is the voice that will be used as a placeholder while copying the other user's actual voice."
        )
        self.gridLayout.addWidget(self.placeholder_ai_voice, 1, 2)

class OptionalAPIInput(SetupDialog):
    def __init__(self):
        super().__init__("OPTIONAL: Please input your Audo.ai and DeepL API keys.")

        self.deepl_api_key = LabeledInput(
            "DeepL API Key",
            configKey="deepl_api_key",
            protected=True,
            fixedLineEditSize=20
        )
        self.gridLayout.addWidget(self.deepl_api_key, 1, 2)

        self.deepl_toggle = ToggleButton(
            "DeepL Translation",
            ["Enabled", "Disabled"],
            [lambda: self.deepl_toggle_visibility(True), lambda: self.deepl_toggle_visibility(False)],
            info="Optional, providers better translation.\nIf a language is not supported by DeepL (or an API key is not provided) Google Translate will be used instead.",
            configKey="deepl_enabled"
        )
        self.gridLayout.addWidget(self.deepl_toggle, 1, 0)
        self.deepl_api_key.setVisible(self.deepl_toggle.get_value() == 0)

        self.audo_api_key = LabeledInput(
            "Audo API Key",
            configKey="audo_api_key",
            protected=True,
            fixedLineEditSize=20
        )
        self.gridLayout.addWidget(self.audo_api_key, 2, 2)

        self.audo_toggle = ToggleButton(
            "Audo.ai enhancement",
            ["Enabled", "Disabled"],
            [lambda: self.audo_toggle_visibility(True), lambda: self.audo_toggle_visibility(False)],
            info="Optional. Enhances the audio when imitating the other user's voice, resulting in a higher quality copy.",
            configKey="audo_enabled"
        )
        self.gridLayout.addWidget(self.audo_toggle, 2, 0)
        self.audo_api_key.setVisible(self.audo_toggle.get_value() == 0)

    def audo_toggle_visibility(self, visible):
        print(f"Audo visibility set to {visible}.")
        self.audo_api_key.setVisible(visible)

    def deepl_toggle_visibility(self, visible):
        print(f"DeepL visibility set to {visible}.")
        self.deepl_api_key.setVisible(visible)

class TranscriptInput(SetupDialog):
    def __init__(self):
        super().__init__("Please choose whether or not you would like to save transcripts of your conversations.")
        self.transcript_save_location = LabeledInput(
            "Transcript save location",
            configKey="transcript_save_location",
            info="This is where transcripts will be saved.",
            infoIsDir=True,
            fixedLineEditSize=20
        )
        self.gridLayout.addWidget(self.transcript_save_location, 1, 2)

        self.transcript_toggle = ToggleButton(
            "Transcription storage",
            ["Enabled", "Disabled"],
            [lambda: self.transcript_toggle_visibility(True), lambda: self.transcript_toggle_visibility(False)],
            info="If enabled, PolyEcho will save a .srt transcript of all audio (both the recognized and translated text) to the specified directory.",
            configKey="transcription_storage"
        )
        self.gridLayout.addWidget(self.transcript_toggle, 1, 0)

        self.transcript_save_location.setVisible(self.transcript_toggle.get_value() == 0)

    def transcript_toggle_visibility(self, visible):
        print(f"Audo visibility set to {visible}.")
        self.transcript_save_location.setVisible(visible)

class SpeechDetectInput(SetupDialog):
    def __init__(self):
        super().__init__("Select your speech detection settings. You can click 'Try' to test them out.")
        self.myEnergyThreshold = LabeledInput(
            "My loudness threshold",
            configKey="my_loudness_threshold",
            data="250",
            info="This indicates how loud you have to be for your voice to be detected.\nShould be kept in the 200-300 range."
        )
        self.gridLayout.addWidget(self.myEnergyThreshold, 1, 0)

        # self.dynamicLoudness = LocalizedCheckbox(configKey="dynamic_loudness",text="Dynamic loudness threshold")
        # self.layout.addWidget(self.dynamicLoudness, 0, 1)

        self.myPauseTime = LabeledInput(
            "My pause time (in seconds)",
            data="0.5",
            configKey="my_pause_time",
            info="This indicates how long you have to pause before a sentence is considered over."
        )
        self.gridLayout.addWidget(self.myPauseTime, 1, 2)

        self.tryButton = QtWidgets.QPushButton(helper.translate_ui_text("Try"))
        self.tryButton.clicked.connect(self.tryButton_click)
        self.gridLayout.addWidget(self.tryButton, 2, 2)



    def tryButton_click(self):
        errorMessage = ""
        try:
            pauseTime = float(self.myPauseTime.get_value())
        except ValueError:
            errorMessage += f"Pause time must be a number"

        try:
            threshold = int(self.myEnergyThreshold.get_value())
        except ValueError:
            errorMessage += f"Loudness threshold must be a number"

        if errorMessage != "":
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText(helper.translate_ui_text(errorMessage))
            msgBox.exec()
            return

        signalEmitter = StrSignalEmitter()
        srSettings = (threshold, False, pauseTime)
        audioDataQueue = queue.Queue()
        detector = Detector(None, settings["audio_input_device"],srSettings, audioDataQueue)

        # Start the detection thread...
        detectorThread = threading.Thread(target=detector.main_loop)
        detectorThread.start()

        msgBox = QtWidgets.QMessageBox(self)
        msgBox.setWindowTitle(helper.translate_ui_text("Speech recognition testing"))
        customOkButton = msgBox.addButton(helper.translate_ui_text("Return"), QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        msgBox.setText(helper.translate_ui_text("Waiting for detection..."))

        def update_message_box(text):
            msgBox.setText(helper.translate_ui_text("Audio detected at:") + f" {text}")

        stopRecEvent = threading.Event()

        def data_consumer_loop():
            while True:
                try:
                    queueData: dict = audioDataQueue.get(timeout=10)
                except queue.Empty:
                    print("Couldn't get an item from the queue within the timeout...")
                    continue
                finally:
                    if stopRecEvent.is_set():
                        print("Stopping detection sample...")
                        break
                # Got an item from the queue, update the messagebox timestamp.
                print("Got an item from the queue.")
                signalEmitter.signal.emit(queueData["endTime"].strftime("%H:%M:%S"))

        signalEmitter.signal.connect(update_message_box)

        #Start the consumer thread...
        consumerThread = threading.Thread(target=data_consumer_loop)
        consumerThread.start()
        msgBox.exec()

        stopRecEvent.set()
        detector.interruptEvent.set()
        consumerThread.join()
        detectorThread.join()
        #We're done with the detection.

class SpeechRecInput(SetupDialog):
    def __init__(self):
        localRecommended = False
        import torch
        if torch.cuda.is_available():
            from pynvml import nvmlInit, nvmlDeviceGetHandleByIndex, nvmlDeviceGetMemoryInfo
            nvmlInit()
            h = nvmlDeviceGetHandleByIndex(0)
            info = nvmlDeviceGetMemoryInfo(h)
            maxVRAM = round(info.total / pow(10, 9), 2)
            if maxVRAM >= 3:    #At least enough VRAM to run the medium model
                localRecommended = True

        prompt = "Please choose which speech recognition mode you'd like to use."
        if localRecommended:
            prompt += "\nYou have an NVIDIA GPU with sufficient VRAM.\nLocal mode is recommended."
        else:
            prompt += "\nYou do not meet the recommended requirements for local mode.\nOnline mode is recommended."
        super().__init__(prompt)

        self.localWhisperWidgets = LocalWidgets()
        self.whisperAPIWidgets = WhisperWidgets()

        self.whisperAPIWidgets.layout.setColumnStretch(0, 0)
        self.whisperAPIWidgets.layout.setColumnStretch(2, 0)

        self.voice_recognition_type = ToggleButton(
            "Voice recognition type",
            ["Local", "Online"],
            [self.on_local, self.on_online],
            info="This is the type of voice recognition.<br>Local runs on your machine, is free, and is the fastest in terms of latency, but the speed depends on your GPU.<br>Online utilizes OpenAI's Whisper API. It has higher latency, but will run on any computer.",
            configKey="voice_recognition_type"
        )
        self.gridLayout.addWidget(self.voice_recognition_type, 1, 1)

        self.gridLayout.addWidget(self.whisperAPIWidgets, 2, 0, 4, 3)
        self.gridLayout.addWidget(self.localWhisperWidgets, 2, 0, 4, 3)

        if localRecommended:
            self.voice_recognition_type.button_clicked(0, self.on_local)
        else:
            self.voice_recognition_type.button_clicked(1, self.on_online)

        self.adjustSize()
        if not localRecommended:
            self.resize(QtCore.QSize(int(self.width()*1.5), self.height()))

    def on_local(self):
        self.whisperAPIWidgets.setVisible(False)
        self.localWhisperWidgets.setVisible(True)
        self.localWhisperWidgets.update_memory_label()

    def on_online(self):
        self.localWhisperWidgets.setVisible(False)
        self.whisperAPIWidgets.setVisible(True)

def run_first_time_setup():
    LanguageInput().exec()
    AudioDeviceInput().exec()
    VirtualInputOutput().exec()
    ElevenLabsInput().exec()
    VoiceInput().exec()
    OptionalAPIInput().exec()
    TranscriptInput().exec()
    SpeechDetectInput().exec()
    temp = SpeechRecInput()
    temp.nextButton.setText(helper.translate_ui_text("Finish"))
    temp.exec()
