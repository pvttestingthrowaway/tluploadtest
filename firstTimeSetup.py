import datetime
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

        saveButton = QtWidgets.QPushButton(helper.translate_ui_text("Save"))
        saveButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        saveButton.setMinimumSize(30, 25)  # adjust the size as per your need
        saveButton.clicked.connect(self.save_clicked)
        self.gridLayout.addWidget(saveButton, 99, 2)    #Just so we're sure it's at the bottom.

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

                if configKey == "openai_api_key":
                    openai.api_key = value
                    try:
                        openai.Model.list()
                    except openai.error.AuthenticationError:
                        errorMessage += "\nOpenAI API error. API Key may be incorrect."

                if configKey == "deepl_api_key" and value != "":
                    deeplTranslator = helper.get_deepl_translator(value, exitOnFail=False)
                    if deeplTranslator is None:
                        errorMessage += "\nDeepL API error. API Key may be incorrect."

                if configKey == "audo_api_key" and value != "":
                    audoClient = helper.get_audo_client(value, exitOnFail=False)
                    if audoClient is None:
                        errorMessage += "\nAudo API error. API Key may be incorrect."

                if configKey == "transcript_save_location":
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

    def closeEvent(self, a0: QtGui.QCloseEvent) -> None:
        if self.check_settings():
            a0.accept()
        else:
            a0.ignore()
class LanguageInput(SetupDialog):
    def __init__(self):
        super().__init__("Please choose the language to use for the application.")

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
        super().__init__("Please set the following devices as your chat program's microphone and speakers.")

        warning = LocalizedCenteredLabel("WARNING: If you would like to use your chat program WITHOUT running PolyEcho, you will need to change them.")
        self.gridLayout.addWidget(warning, 1, 1)

        virtualDevices = helper.get_virtual_devices()
        input_label = LocalizedCenteredLabel("Input device")
        self.virtual_input = CenteredLabel(virtualDevices["you"]["input"])
        output_label = LocalizedCenteredLabel("Output device")
        self.virtual_output = CenteredLabel(virtualDevices["them"]["output"])

        self.gridLayout.addWidget(input_label, 2, 0)
        self.gridLayout.addWidget(self.virtual_input, 3, 0)
        self.gridLayout.addWidget(output_label, 2, 2)
        self.gridLayout.addWidget(self.virtual_output, 3, 2)

class ElevenLabsInput(SetupDialog):
    def __init__(self):
        super().__init__("Please input your ElevenLabs API Key.")

        self.elevenlabs_api_key = LabeledInput(
            "ElevenLabs API Key",
            configKey="elevenlabs_api_key",
            info="You can find your API Key under your Profile, on the website.",
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
            info="This is the voice that will be used as a placeholder while cloning the user's actual voice."
        )
        self.gridLayout.addWidget(self.placeholder_ai_voice, 1, 2)

class OptionalAPIInput(SetupDialog):
    def __init__(self):
        super().__init__("OPTIONAL: Please input your Audo.ai and DeepL API keys.")

        self.deepl_api_key = LabeledInput(
            "DeepL API Key (Optional)",
            configKey="deepl_api_key",
            protected=True,
            info="Optional. If a language is not supported by DeepL (or an API key is not provided) Google Translate will be used instead."
        )
        self.gridLayout.addWidget(self.deepl_api_key, 1, 0)

        self.audo_api_key = LabeledInput(
            "Audo API Key (Optional)",
            configKey="audo_api_key",
            protected=True,
            info="Optional. Enhances the audio for clone creation, resulting in a higher quality clone."
        )
        self.gridLayout.addWidget(self.audo_api_key, 1, 2)

class SpeechDetectInput(SetupDialog):
    def __init__(self):
        super().__init__("Select your speech detection settings. You can click 'Try' to test them out.")
        self.myEnergyThreshold = LabeledInput(
            "My loudness threshold",
            configKey="my_loudness_threshold",
            data="250"
        )
        self.gridLayout.addWidget(self.myEnergyThreshold, 1, 0)

        # self.dynamicLoudness = LocalizedCheckbox(configKey="dynamic_loudness",text="Dynamic loudness threshold")
        # self.layout.addWidget(self.dynamicLoudness, 0, 1)

        self.myPauseTime = LabeledInput(
            "My pause time (in seconds)",
            data="0.5",
            configKey="my_pause_time"
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
            prompt += "\nSince you have an NVIDIA GPU with sufficient VRAM, local mode is recommended."
        else:
            prompt += "\nYou do not meet the recommended requirements for local mode. Online mode is recommended."
        super().__init__(prompt)

        self.localWhisperWidgets = LocalWidgets()
        self.whisperAPIWidgets = WhisperWidgets()

        self.whisperAPIWidgets.layout.setColumnStretch(0, 0)
        self.whisperAPIWidgets.layout.setColumnStretch(2, 0)

        self.voice_recognition_type = ToggleButton(
            "Voice recognition type",
            ["Local", "Online"],
            [self.on_local, self.on_online],
            info="This is the type of voice recognition.",
            configKey="voice_recognition_type"
        )
        self.gridLayout.addWidget(self.voice_recognition_type, 1, 1)

        self.gridLayout.addWidget(self.whisperAPIWidgets, 2, 0, 4, 3)
        self.gridLayout.addWidget(self.localWhisperWidgets, 2, 0, 4, 3)

        if localRecommended:
            self.voice_recognition_type.button_clicked(0, self.on_local)
        else:
            self.voice_recognition_type.button_clicked(1, self.on_online)


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
    SpeechDetectInput().exec()
    SpeechRecInput().exec()
