import copy
import datetime
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Optional, TextIO
from zipfile import ZipFile

import elevenlabslib
import keyring
import requests

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import QSize, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QGridLayout, QPushButton, QWidget, QSizePolicy, QMessageBox

from utils import helper
from utils.helper import settings

from configWindow import LabeledInput, ConfigDialog, ToggleButton, CenteredLabel, LocalizedCenteredLabel
from interpreter import Interpreter

greenColor = "green"
yellowColor = "yellow"
redColor = "red"

class ResizableCircularButton(QPushButton):
    def __init__(self, bgColor, icon=None, *args, **kwargs):
        super(ResizableCircularButton, self).__init__(*args, **kwargs)
        self.bgColor = None
        self.previousColor = None
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHeightForWidth(True)
        self.setSizePolicy(sizePolicy)
        if icon is not None:
            self.setIcon(icon)

        self.setColor(bgColor)
        self.bgColor = bgColor
        self.previousColor = bgColor

    def heightForWidth(self, width):
        return width

    def setColor(self, bgColor):
        if self.bgColor != bgColor: #If it's the same, don't change anything.
            self.previousColor = self.bgColor
            self.bgColor = bgColor
        size = min(self.width(), self.height())
        self.setStyleSheet(f"border-radius : {int(size / 2)}; background-color: {self.bgColor}; border :5px solid black;")

    def getColor(self):
        return self.bgColor

    def getPreviousColor(self):
        return self.previousColor

    def resizeEvent(self, a0: QtGui.QResizeEvent) -> None:
        size = min(self.width(), self.height())
        self.setStyleSheet(f"border-radius : {int(size / 2)}; background-color: {self.bgColor}; border :5px solid black;")
        iconPadding = int(size/5)
        self.setIconSize(QSize(size - iconPadding, size - iconPadding))


class MainWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.transcript:Optional[TextIO] = None
        self.micButton = None
        self.speakerButton = None
        self.activeLabels = None
        self.myInterpreter:Optional[Interpreter] = None
        self.theirInterpreter:Optional[Interpreter] = None
        self.layout = QGridLayout(self)

        self.inactiveLayout = QWidget()
        self.inactiveLayout.setLayout(self.init_inactive_state())

        self.activeLayout = QWidget()
        self.activeLayout.setLayout(self.init_active_state())

        self.configDialog = ConfigDialog()
        self.layout.addWidget(self.activeLayout)
        self.layout.addWidget(self.inactiveLayout)
        self.set_state("inactive")

    def set_state(self, state:str):
        if state != "active" and state != "inactive":
            raise RuntimeError("Invalid state.")
        self.inactiveLayout.setVisible(state=="inactive")
        self.activeLayout.setVisible(state=="active")
    def reset_active_layout(self):
        self.activeLabels["me"]["recognized"].setText("MyText - Recognized")
        self.activeLabels["me"]["translated"].setText("MyText - Translated")
        self.activeLabels["them"]["recognized"].setText("TheirText - Recognized")
        self.activeLabels["them"]["translated"].setText("TheirText - Translated")

        self.activeLabels["cloneProgress"].setText("Cloning progress...")
        self.micButton.setColor(greenColor)

    def init_active_state(self):
        active_layout = QGridLayout()

        # Create labels
        self.activeLabels = dict()
        self.activeLabels["me"] = dict()
        self.activeLabels["them"] = dict()
        self.activeLabels["me"]["recognized"] = CenteredLabel("MyText - Recognized")
        self.activeLabels["me"]["translated"] = CenteredLabel("MyText - Translated")
        self.activeLabels["them"]["recognized"] = CenteredLabel("TheirText - Recognized")
        self.activeLabels["them"]["translated"] = CenteredLabel("TheirText - Translated")

        self.activeLabels["cloneProgress"] = LocalizedCenteredLabel("Cloning progress...")

        # Create circular buttons with icons
        self.micButton = ResizableCircularButton(greenColor, QIcon('resources/microphone.png'))
        self.speakerButton = ResizableCircularButton(yellowColor, QIcon('resources/speaker.png'))

        self.reset_active_layout()

        # Create rectangular button
        self.stop_button = QPushButton(helper.translate_ui_text("Stop", settings["ui_language"]))
        self.stop_button.clicked.connect(self.stop_clicked)

        # Set active layout
        active_layout.addWidget(self.activeLabels["me"]["recognized"], 0, 0)
        active_layout.addWidget(self.activeLabels["them"]["recognized"], 0, 2)
        active_layout.addWidget(self.micButton, 1, 0)

        active_layout.addWidget(self.speakerButton, 1, 2)
        active_layout.addWidget(self.activeLabels["me"]["translated"], 2, 0)
        active_layout.addWidget(self.activeLabels["them"]["translated"], 2, 2)
        active_layout.addWidget(self.stop_button, 3, 1)
        active_layout.addWidget(self.activeLabels["cloneProgress"], 3, 2)

        for i in range(3):
            active_layout.setColumnStretch(i, 1)

        for i in range(4):
            active_layout.setRowStretch(i, 1)

        return active_layout

    def init_inactive_state(self) -> QGridLayout:
        # Initialize layout
        inactive_layout = QtWidgets.QGridLayout(self)

        self.user = None
        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        if apiKey is not None:
            try:
                self.user:elevenlabslib.ElevenLabsUser = elevenlabslib.ElevenLabsUser(apiKey)
            except (ValueError, AttributeError):
                pass

        # First row
        self.your_output_lang = LabeledInput(
            "Your output language",
            configKey = "your_output_language",
            data=helper.get_supported_languages_localized(self.user, settings["ui_language"]),
            fixedComboBoxSize=None
        )
        inactive_layout.addWidget(self.your_output_lang, 0, 0)

        self.their_output_lang = LabeledInput(
            "Their output language",
            configKey="their_output_language",
            data = helper.get_supported_languages_localized(self.user, settings["ui_language"]),
            fixedComboBoxSize=None
        )
        inactive_layout.addWidget(self.their_output_lang, 0, 2)


        self.nameInput = LabeledInput(
            "Insert the name for the new voice",
            info="The placeholder voice defined in settings will be used until the clone is complete.",
            configKey="name_input"
        )
        inactive_layout.addWidget(self.nameInput, 2, 1)
        self.nameInput.line_edit.setFixedWidth(int(self.nameInput.line_edit.width() / 3))


        self.voicePicker = LabeledInput(
            "Select an existing voice",
            data=helper.get_list_of_voices(self.user),
            info="The placeholder voice will not be used, and a new clone will not be created.",
            configKey="voice_picker"
        )

        self.voicePicker.combo_box.setFixedWidth(self.nameInput.line_edit.width())
        inactive_layout.addWidget(self.voicePicker, 2, 1)
        self.voiceType = None
        if self.user is not None and self.user.get_voice_clone_available():
            # Second row
            self.voiceType = ToggleButton(
                "Output Voice",
                ["Create new", "Re-use"],
                [self.on_new, self.on_reuse],
                configKey="voice_type"
            )
            inactive_layout.addWidget(self.voiceType, 1, 1)
        else:
            self.nameInput.setVisible(False)
            self.voicePicker.setVisible(True)


        # Third row
        settings_button = QPushButton(helper.translate_ui_text("Settings", settings["ui_language"]))
        settings_button.clicked.connect(self.show_settings)  # connect to method
        inactive_layout.addWidget(settings_button, 3, 0)

        self.start_button = QtWidgets.QPushButton(helper.translate_ui_text("Start", settings["ui_language"]))
        self.start_button.setStyleSheet("background-color: green")
        self.start_button.clicked.connect(self.start_clicked)  # connect to method
        inactive_layout.addWidget(self.start_button, 3, 2)

        if self.user is None:
            self.start_button.setEnabled(False)

        for i in range(3):
            inactive_layout.setColumnStretch(i, 1)

        for i in range(5):
            inactive_layout.setRowStretch(i, 1)

        return inactive_layout

    def start_clicked(self):
        assert (self.user is not None)

        #Update settings
        cloneNew = False
        if self.voiceType is not None:
            cloneNew = self.voiceType.get_value() == 0

        if cloneNew and self.user.get_voice_clone_available():
            self.user:elevenlabslib.ElevenLabsUser

            if self.nameInput.line_edit.text() == "":
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText("The voice name cannot be empty!")
                msgBox.exec()
                return

            voiceMax = self.user.get_user_data()["voice_limit"]
            currentVoiceAmount = len(self.user.get_available_voices())
            if currentVoiceAmount >= voiceMax:
                msgBox = QtWidgets.QMessageBox()
                msgBox.setWindowTitle("Out of voice slots!")
                msgBox.setText("You've run out of voice slots.")
                msgBox.buttonOk = msgBox.addButton(self.tr("Ok"), QMessageBox.ButtonRole.AcceptRole)
                msgBox.buttonCancel = msgBox.addButton(self.tr("Cancel"), QMessageBox.ButtonRole.RejectRole)
                voicesAvailableForDeletion = []
                for voice in self.user.get_available_voices():
                    if voice.category != "premade" and voice.category != "professional":
                        voicesAvailableForDeletion.append(f"{voice.initialName} - {voice.voiceID}")

                msgBox.voicePicker = LabeledInput("Please choose which voice to delete.", data=voicesAvailableForDeletion, configKey="voice_deletion")
                msgBox.layout().addWidget(msgBox.voicePicker)

                def okClicked():
                    voiceName = msgBox.voicePicker.combo_box.currentText()
                    voiceToDelete = self.user.get_voice_by_ID(voiceName[voiceName.index(" - ")+3:])
                    voiceToDelete.delete_voice()
                    msgBox.close()


                msgBox.buttonOk.clicked.connect(okClicked)
                msgBox.buttonCancel.clicked.connect(msgBox.close)

                msgBox.exec()
                newVoiceAmount = len(self.user.get_available_voices())
                if newVoiceAmount == currentVoiceAmount:
                    return

        #Update settings
        settings["your_output_language"] = self.your_output_lang.combo_box.currentText()
        settings["their_output_language"] = self.their_output_lang.combo_box.currentText()
        helper.dump_settings()

        #Check audio device validity
        inputInfo = None
        outputInfo = None
        try:
            inputInfo = helper.get_portaudio_device_info_from_name(settings["audio_input_device"], "input")
        except RuntimeError:
            settings["audio_input_device"] = "Default"

        try:
            outputInfo = helper.get_portaudio_device_info_from_name(settings["audio_output_device"], "output")
        except RuntimeError:
            settings["audio_output_device"] = "Default"

        if inputInfo is None or outputInfo is None:
            with open("config.json", "w") as fp:
                json.dump(settings, fp, indent=4)
            msgBox = QtWidgets.QMessageBox()
            text = "Your "
            if inputInfo is None:
                text += "input "
            if outputInfo is None:
                if inputInfo is None:
                    text += "and output devices are no longer valid.\nThey've been reset to default. Head to the settings page if you'd like to modify them."
                else:
                    text += "output device is no longer valid.\nIt was reset to default. Head to the settings page if you'd like to modify it."
            else:
                text += "device is no longer valid.\nIt was reset to default. Head to the settings page if you'd like to modify it."
            msgBox.setText(text)
            msgBox.exec()
            return


        myVirtualOutput = ""
        theirVirtualInput = ""
        for deviceName in helper.get_list_of_portaudio_devices("output", True):
            if "cable-a" in deviceName.lower():
                myVirtualOutput = deviceName
                break

        for deviceName in helper.get_list_of_portaudio_devices("input", True):
            if "cable-b" in deviceName.lower():
                theirVirtualInput = deviceName
                break

        # audioInput:str, audioOutput:str, settings:dict, targetLang:str, voiceIDOrName:str
        mysrSettings = (settings["my_loudness_threshold"], False, settings["my_pause_time"])    #Removed dynamic_loudness
        theirsrSettings = (settings["their_loudness_threshold"], False, settings["their_pause_time"])  # Removed dynamic_loudness

        self.myInterpreter = Interpreter(settings["audio_input_device"], myVirtualOutput, settings, settings["your_output_language"], settings["your_ai_voice"], srSettings=mysrSettings)

        # TODO: remove this because it's only for testing
        theirVirtualInput = "Microphone (USB-MIC) - 5"
        #TODO: TEST THIS.
        if cloneNew:
            self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], voiceIDOrName=self.nameInput.line_edit.text(),createNewVoice=True, srSettings=theirsrSettings)
        else:
            self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], voiceIDOrName=self.voicePicker.combo_box.currentText(), )

        self.set_state("active")
        self.reset_active_layout()

        if cloneNew:
            self.activeLabels["cloneProgress"].setVisible(True)
            self.speakerButton.setColor(yellowColor)
            self.theirInterpreter.cloneProgressSignal.connect(lambda cloneProgress: self.setCloneProgress(cloneProgress))
        else:
            self.activeLabels["cloneProgress"].setVisible(False)
            self.speakerButton.setColor(greenColor)

        self.myInterpreter.textReadySignal.connect(lambda recognizedText, translatedText: self.setSpeechLabelsText("me", recognizedText, translatedText))
        self.theirInterpreter.textReadySignal.connect(lambda recognizedText, translatedText: self.setSpeechLabelsText("them", recognizedText, translatedText))

        self.micButton.clicked.connect(self.micbutton_click)
        self.speakerButton.clicked.connect(self.speakerbutton_click)

        if settings["transcription_storage"] == 0:
            transcriptName = datetime.datetime.now().strftime("%Y-%m-%d - %H.%M.%S.log")
            self.transcript = open(os.path.join(settings["transcript_save_location"],transcriptName),"w")

        self.myInterpreter.begin_interpretation()
        #time.sleep(10)
        self.theirInterpreter.begin_interpretation()



    def setCloneProgress(self, progressText):
        try:
            progressAmount = float(progressText)
        except ValueError:
            progressAmount = None

        if progressAmount is not None:
            self.activeLabels["cloneProgress"].setText(f"Cloning progress: {progressAmount}/180 seconds recorded...")
        else:
            if progressText == "PROCESSING":
                self.activeLabels["cloneProgress"].setText(f"Necessary data recorded, processing...")
            elif progressText == "COMPLETE":
                self.activeLabels["cloneProgress"].setText(f"Clone complete!")
                if self.speakerButton.getColor() != redColor:
                    self.speakerButton.setColor(greenColor)
                else:
                    self.speakerButton.previousColor = greenColor

    def setSpeechLabelsText(self, who, recognizedText, translatedText):
        try:
            self.activeLabels[who]["recognized"].setText(recognizedText)
            self.activeLabels[who]["translated"].setText(translatedText)

            if self.transcript is not None:
                identifier = f"{who[0].upper() + who[1:]}@{datetime.datetime.now().strftime('%H:%M:%S')}"
                self.transcript.write(f"{identifier} (Original) - {recognizedText}\n")
                self.transcript.write(f"{identifier} (Translated) - {translatedText}\n\n")
                self.transcript.flush()
        except RuntimeError as e:
            pass



    def micbutton_click(self):
        if self.micButton.getColor() == redColor:
            #Already paused
            self.micButton.setColor(greenColor)
            self.myInterpreter.detector_paused = False
        else:
            #Not paused
            self.micButton.setColor(redColor)
            self.myInterpreter.detector_paused = True


    def speakerbutton_click(self):
        if self.speakerButton.getColor() == redColor:
            # Already paused
            self.speakerButton.setColor(self.speakerButton.getPreviousColor())
            self.theirInterpreter.synthetizer_paused = False
        else:
            # Not paused
            self.speakerButton.setColor(redColor)
            self.theirInterpreter.synthetizer_paused = True


    def stop_clicked(self):
        self.myInterpreter.detector_paused = False
        self.theirInterpreter.synthetizer_paused = False
        self.myInterpreter.stop_interpretation()
        self.theirInterpreter.stop_interpretation()
        if self.transcript is not None:
            self.transcript.flush()
        self.transcript = None
        self.set_state("inactive")


    def on_new(self):
        self.nameInput.setVisible(True)
        self.voicePicker.setVisible(False)
    def on_reuse(self):
        self.nameInput.setVisible(False)
        self.voicePicker.setVisible(True)

    def show_settings(self):
        currentVoiceType = self.voiceType.get_value()
        currentPickedVoice = self.voicePicker.get_value()
        currentVoiceName = self.nameInput.get_value()
        oldSettings = copy.deepcopy(settings)
        oldXIKey = keyring.get_password("polyecho", "elevenlabs_api_key")

        QTimer.singleShot(1, lambda: (self.configDialog.activateWindow(), self.configDialog.raise_()))
        self.configDialog.exec()

        newXIKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        if oldSettings["ui_language"] != settings["ui_language"] or oldXIKey != newXIKey:
            self.configDialog = ConfigDialog()

            self.layout.removeWidget(self.inactiveLayout)
            self.layout.removeWidget(self.activeLayout)

            self.inactiveLayout = QWidget()
            self.inactiveLayout.setLayout(self.init_inactive_state())
            self.activeLayout = QWidget()
            self.activeLayout.setLayout(self.init_active_state())

            self.layout.addWidget(self.activeLayout)
            self.layout.addWidget(self.inactiveLayout)

            self.set_state("inactive")
            if currentVoiceType == 0:
                self.voiceType.button_clicked(currentVoiceType, self.on_new)
            else:
                self.voiceType.button_clicked(currentVoiceType, self.on_reuse)
            self.nameInput.line_edit.setText(currentVoiceName)

            allItems = [self.voicePicker.combo_box.itemText(i) for i in range(self.voicePicker.combo_box.count())]
            if currentPickedVoice in allItems:
                self.voicePicker.combo_box.setCurrentIndex(allItems.index(currentPickedVoice))
            else:
                self.voicePicker.combo_box.setCurrentIndex(0)

#Helper functions for ffmpeg download/extract
class SignalEmitter(QObject):
    download_finished = pyqtSignal()
def download_ffmpeg(urls, downloadDir, extractDir, currentOS):
    message_box = QMessageBox()
    message_box.setText(helper.translate_ui_text("Downloading FFmpeg. Please wait...", "default - syslang"))
    message_box.setStandardButtons(QMessageBox.StandardButton.NoButton)  # No buttons
    signal_emitter = SignalEmitter()
    signal_emitter.download_finished.connect(lambda: message_box.done(0))

    def download_thread_fn():
        for url in urls:
            if currentOS == 'Windows':
                fileName = url.split('/')[-1]
            else:
                fileName = url.split('/')[-2]
                if fileName == "get":
                    fileName = "ffmpeg"
            downloadPath = os.path.join(downloadDir, f'{fileName}.zip')
            try:
                r = requests.get(url, stream=True)
                with open(downloadPath, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                extract_ffmpeg(downloadPath, extractDir)
            except Exception as e:
                print(e)
                shutil.rmtree(extractDir)  # Clean up completely
                signal_emitter.download_finished.emit()

        shutil.rmtree(downloadDir, ignore_errors=True)  # Clean up
        signal_emitter.download_finished.emit()

    os.makedirs(downloadDir, exist_ok=True)
    download_thread = threading.Thread(target=download_thread_fn)
    download_thread.start()
    QTimer.singleShot(1, lambda: (message_box.activateWindow(), message_box.raise_()))
    message_box.exec()

def extract_ffmpeg(file_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    with ZipFile(file_path, 'r') as zip_ref:
        if platform.system() == 'Windows':
            files_to_extract = [name for name in zip_ref.namelist() if '/bin/' in name and ".exe" in name]
            for file in files_to_extract:
                with zip_ref.open(file) as source, open(os.path.join(output_dir, os.path.basename(file)), 'wb') as target:
                    shutil.copyfileobj(source, target)
        else:
            zip_ref.extractall(output_dir)

def main():
    app = QApplication([])

    try:
        subprocess.check_output('ffmpeg -version', shell=True)
    except subprocess.CalledProcessError:
        #ffmpeg is not in $PATH.
        currentOS = platform.system()
        if currentOS != "Windows" and currentOS != "Darwin":
            message_box = QMessageBox()
            message_box.setText("FFmpeg is missing, but your OS is not supported for auto-download. Please install it yourself.")
            QTimer.singleShot(1, lambda: (message_box.activateWindow(), message_box.raise_()))
            message_box.exec()
            exit()


        os.makedirs(os.path.join(os.getcwd(),"ffmpeg-bin"), exist_ok=True)

        if not os.path.exists(f"ffmpeg-bin/ffmpeg{'.exe' if currentOS == 'Windows' else ''}"):
            #It's not downloaded either. Download it.
            downloadDir = os.path.join(os.getcwd(),"ffmpeg-dl")
            extractDir = os.path.join(os.getcwd(), 'ffmpeg-bin')

            if currentOS == 'Windows':
                urls = ['https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip']
            elif currentOS == 'Darwin':
                urls = ['https://evermeet.cx/ffmpeg/get/zip', 'https://evermeet.cx/ffmpeg/get/ffprobe/zip', 'https://evermeet.cx/ffmpeg/get/ffplay/zip']
            else:
                raise Exception("Unsupported OS")

            download_ffmpeg(urls, downloadDir, extractDir, currentOS)
            if not os.path.exists("ffmpeg-bin/ffmpeg.exe"):
                raise Exception("Download failed! Please try again.")


        #At this point the binary files for ffmpeg are in ffmpeg-bin in the current directory.
        os.environ["PATH"] += os.pathsep + os.path.join(os.getcwd(),"ffmpeg-bin")


    #TODO: First-time setup if config doesn't exist.
    dialog = MainWindow()
    dialog.show()               #It crashes in debug mode with an access violation unless I put a breakpoint here. What the fuck?
    dialog.activateWindow()
    dialog.raise_()


    app.exec()

    try:
        settings["your_output_language"] = dialog.your_output_lang.combo_box.currentText()
        settings["their_output_language"] = dialog.their_output_lang.combo_box.currentText()
        helper.dump_settings()
    except RuntimeError:
        pass

if __name__ == '__main__':
    main()
