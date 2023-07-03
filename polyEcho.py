import copy
import datetime
import gc
import json
import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Optional
from zipfile import ZipFile

import elevenlabslib
import keyring
import requests
import srt

import tracemalloc

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import QSize, pyqtSignal, QObject, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QGridLayout, QPushButton, QWidget, QSizePolicy, QMessageBox, QLabel, QProgressBar
from srt import Subtitle

import firstTimeSetup
from utils import helper
from utils.helper import settings
from utils.customWidgets import *

from configWindow import LabeledInput, ConfigDialog, ToggleButton, CenteredLabel, LocalizedCenteredLabel, SignalEmitter
from interpreter import Interpreter


class MainWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super(MainWindow, self).__init__(parent)
        self.transcript:Optional[dict] = None
        self.micButton = None
        self.speakerButton = None
        self.activeLabels = None
        self.yourInterpreter:Optional[Interpreter] = None
        self.theirInterpreter:Optional[Interpreter] = None
        self.layout = QGridLayout(self)

        self.inactiveLayout = QWidget()
        self.inactiveLayout.setLayout(self.init_inactive_state())

        self.activeLayout = QWidget()
        self.activeLayout.setLayout(self.init_active_state())

        self.configDialog = None
        self.layout.addWidget(self.activeLayout)
        self.layout.addWidget(self.inactiveLayout)
        self.set_state("inactive")
        self.setWindowTitle("PolyEcho")

    def set_state(self, state:str):
        if state != "active" and state != "inactive":
            raise RuntimeError("Invalid state.")
        self.inactiveLayout.setVisible(state=="inactive")
        self.activeLayout.setVisible(state=="active")
    def reset_active_layout(self):
        self.activeLabels["you"]["recognized"].setText(helper.translate_ui_text("Your recognized text"))
        self.activeLabels["you"]["translated"].setText(helper.translate_ui_text("Your translated text"))
        self.activeLabels["them"]["recognized"].setText(helper.translate_ui_text("Their recognized text"))
        self.activeLabels["them"]["translated"].setText(helper.translate_ui_text("Their translated text"))

        self.activeLabels["cloneProgress"].setText("Cloning progress...")
        self.micButton.setColor(helper.colors_dict['green'])

    def init_active_state(self):
        active_layout = QGridLayout()

        # Create labels
        self.activeLabels = dict()
        self.activeLabels["you"] = dict()
        self.activeLabels["them"] = dict()
        self.activeLabels["you"]["recognized"] = CenteredLabel(wordWrap=True)
        self.activeLabels["you"]["translated"] = CenteredLabel(wordWrap=True)
        self.activeLabels["them"]["recognized"] = CenteredLabel(wordWrap=True)
        self.activeLabels["them"]["translated"] = CenteredLabel(wordWrap=True)
        self.activeLabels["cloneProgress"] = LocalizedCenteredLabel(cacheSkip=True, wordWrap=True)


        micLabels = [self.activeLabels["you"]["recognized"], self.activeLabels["you"]["translated"]]
        speakerLabels = [self.activeLabels["them"]["recognized"], self.activeLabels["them"]["translated"], self.activeLabels["cloneProgress"]]

        # Create circular buttons with icons
        self.micButton = AudioButton(helper.colors_dict['green'], QIcon('resources/microphone.png'), assignedLabels=micLabels)
        self.micButton.setAccessibleName("Your mute button")
        self.micButton.setAccessibleDescription("Allows you to mute yourself. You are currently not muted.")
        self.speakerButton = AudioButton(helper.colors_dict['yellow'], QIcon('resources/speaker.png'), assignedLabels=speakerLabels)
        self.speakerButton.setAccessibleName("Their mute button")
        self.micButton.setAccessibleDescription("Allows you to mute the other user. They are currently not muted.")
        self.reset_active_layout()

        # Create rectangular button
        self.stop_button = QPushButton(helper.translate_ui_text("Stop"))
        self.stop_button.setStyleSheet(f"background-color: {helper.colors_dict['red']}")
        self.stop_button.clicked.connect(self.stop_clicked)



        # Set active layout
        active_layout.addWidget(self.activeLabels["you"]["recognized"], 0, 0)
        active_layout.addWidget(self.activeLabels["them"]["recognized"], 0, 2)
        active_layout.addWidget(self.micButton, 1, 0)

        active_layout.addWidget(self.speakerButton, 1, 2)
        active_layout.addWidget(self.activeLabels["you"]["translated"], 2, 0)
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

        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        self.user: elevenlabslib.ElevenLabsUser = helper.get_xi_user(apiKey, exitOnFail=False)

        # First row
        self.your_output_lang = LabeledInput(
            "Your output language",
            configKey = "your_output_language",
            data=helper.get_supported_languages_localized(self.user, settings["ui_language"]),
            fixedComboBoxSize=None,
            info="The language you would like your TTS voice to speak in."
        )
        inactive_layout.addWidget(self.your_output_lang, 0, 0)

        self.their_output_lang = LabeledInput(
            "Their output language",
            configKey="their_output_language",
            data = helper.get_supported_languages_localized(self.user, settings["ui_language"]),
            fixedComboBoxSize=None,
            info="The language you would like their TTS voice to speak in."
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
        settings_button = QPushButton(helper.translate_ui_text("Settings"))
        settings_button.clicked.connect(self.show_settings)  # connect to method
        inactive_layout.addWidget(settings_button, 3, 0)

        self.start_button = QtWidgets.QPushButton(helper.translate_ui_text("Start"))
        self.start_button.setStyleSheet(f"background-color: {helper.colors_dict['green']}")
        self.start_button.clicked.connect(self.start_clicked)  # connect to method
        inactive_layout.addWidget(self.start_button, 3, 2)

        if self.user is None:
            self.start_button.setEnabled(False)

        for i in range(3):
            inactive_layout.setColumnStretch(i, 1)

        for i in range(5):
            inactive_layout.setRowStretch(i, 1)

        return inactive_layout

    def start_clicked(self, dummyArgForMemProfiler=None):
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
                msgBox.setWindowTitle(helper.translate_ui_text("Out of voice slots!"))
                msgBox.setText(helper.translate_ui_text("You've run out of voice slots."))
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
            msgBox.setText(helper.translate_ui_text(text))
            msgBox.exec()
            return

        virtualDevices = helper.get_virtual_devices()
        yourVirtualOutput = virtualDevices["you"]["output"]
        theirVirtualInput = virtualDevices["them"]["input"]
        theirVirtualInput = "Microphone (USB-MIC) - 5"

        if yourVirtualOutput is None or theirVirtualInput is None:
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText(helper.translate_ui_text("FATAL: Could not find virtual audio devices. Run first time setup again."))
            msgBox.exec()
            return

        # audioInput:str, audioOutput:str, settings:dict, targetLang:str, voiceIDOrName:str
        yoursrSettings = (settings["my_loudness_threshold"], False, settings["my_pause_time"])    #Removed dynamic_loudness
        theirsrSettings = (settings["their_loudness_threshold"], False, settings["their_pause_time"])  # Removed dynamic_loudness

        messageBox = QMessageBox()
        messageBox.setWindowTitle(helper.translate_ui_text("Starting..."))
        runLocal = settings["voice_recognition_type"] == 0
        if runLocal and "downloaded_models" not in settings:
            settings["downloaded_models"] = []
            helper.dump_settings()

        if runLocal and settings["model_size"] not in settings["downloaded_models"]:
            settings["downloaded_models"].append(settings["model_size"])
            helper.dump_settings()
            messageBox.setText(helper.translate_ui_text("Setting up interpreters. Downloading a whisper model, so this may a while..."))
        else:
            messageBox.setText(helper.translate_ui_text("Setting up interpreters, please wait..."))
        messageBox.setStandardButtons(QMessageBox.StandardButton.NoButton)  # No buttons
        signalEmitter = SignalEmitter()
        signalEmitter.signal.connect(lambda: messageBox.done(0))
        helper.print_usage_info("Before interpreter setup")
        def interpreter_setup():
            self.yourInterpreter = Interpreter(settings["audio_input_device"], yourVirtualOutput, settings, settings["your_output_language"], settings["your_ai_voice"], srSettings=yoursrSettings)
            helper.print_usage_info("After your interpreter")
            # TODO: remove this because it's only for testing
            if cloneNew:
                self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], voiceIDOrName=self.nameInput.line_edit.text(),
                                                    createNewVoice=True, srSettings=theirsrSettings)
            else:
                self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"],
                                                    voiceIDOrName=self.voicePicker.combo_box.currentText(), srSettings=theirsrSettings)
            helper.print_usage_info("After their interpreter")
            signalEmitter.signal.emit()


        interpreterThread = threading.Thread(target=interpreter_setup)
        interpreterThread.start()
        QTimer.singleShot(1, lambda: (messageBox.activateWindow(), messageBox.raise_()))
        messageBox.exec()
        print("Interpreter setup completed")

        self.set_state("active")
        self.reset_active_layout()

        if cloneNew:
            self.activeLabels["cloneProgress"].setVisible(True)
            self.speakerButton.setColor(helper.colors_dict['yellow'])
            self.theirInterpreter.cloneProgressSignal.connect(lambda cloneProgress: self.setCloneProgress(cloneProgress))
        else:
            self.activeLabels["cloneProgress"].setVisible(False)
            self.speakerButton.setColor(helper.colors_dict['green'])

        self.yourInterpreter.textReadySignal.connect(lambda signalData: self.setSpeechLabelsText("you", signalData))
        self.theirInterpreter.textReadySignal.connect(lambda signalData: self.setSpeechLabelsText("them", signalData))

        self.micButton.clicked.connect(self.micbutton_click)
        self.speakerButton.clicked.connect(self.speakerbutton_click)

        if settings["transcription_storage"] == 0:
            self.transcript = dict()
            self.transcript["start"] = datetime.datetime.now()
            self.transcript["lock"] = threading.Lock()
            transcriptName = self.transcript["start"].strftime("%Y-%m-%d - %H.%M.%S.srt")
            self.transcript["file"] = open(os.path.join(settings["transcript_save_location"],transcriptName),"w")

        self.yourInterpreter.begin_interpretation()
        #time.sleep(10)
        self.theirInterpreter.begin_interpretation()



    def setCloneProgress(self, progressText):
        try:
            progressAmount = float(progressText)
            progressAmount = int(progressAmount)
        except ValueError:
            progressAmount = None

        if progressAmount is not None:
            self.activeLabels["cloneProgress"].setText(f"Cloning progress: {progressAmount}/180 seconds recorded...")
        else:
            if progressText == "PROCESSING":
                self.activeLabels["cloneProgress"].setText(f"Necessary data recorded, processing...")
            elif progressText == "COMPLETE":
                self.activeLabels["cloneProgress"].setText(f"Clone complete!")
                if self.speakerButton.getColor() != helper.colors_dict['red']:
                    self.speakerButton.setColor(helper.colors_dict['green'])
                else:
                    self.speakerButton.previousColor = helper.colors_dict['green']

    def setSpeechLabelsText(self, who, signalData:dict):
        try:
            self.activeLabels[who]["recognized"].setText(signalData["recognized"])
            self.activeLabels[who]["translated"].setText(signalData["translated"])
            self.micButton.resizeEvent(None)
            self.speakerButton.resizeEvent(None)
            if self.transcript is not None:
                with self.transcript["lock"]:
                    signalData["startTime"] -= self.transcript["start"]
                    signalData["endTime"] -= self.transcript["start"]

                    if "subtitles" not in self.transcript:
                        self.transcript["subtitles"] = list()
                    content = f"Original: {signalData['recognized']}\nTranslated: {signalData['translated']}"
                    newIndex=1
                    if len(self.transcript["subtitles"]) > 0:
                        newIndex = self.transcript["subtitles"][-1].index+1
                    newSub = Subtitle(index=newIndex, start=signalData["startTime"],end=signalData["endTime"], content=srt.make_legal_content(content))
                    self.transcript["subtitles"].append(newSub)

                    #Let's ensure they're all ordered properly:
                    self.transcript["subtitles"] = list(srt.sort_and_reindex(self.transcript["subtitles"]))

                    self.transcript["file"].write(newSub.to_srt(strict=False))
                    self.transcript["file"].flush()
        except RuntimeError as e:
            pass




    def micbutton_click(self):
        print("Clicked mic button")
        if self.micButton.getColor() == helper.colors_dict['red']:
            #Already paused
            print("Unpausing mic")
            self.micButton.setColor(helper.colors_dict['green'])
            self.yourInterpreter.detector_paused = False
            self.micButton.setAccessibleDescription("Allows you to mute yourself. You are currently not muted.")
        else:
            #Not paused
            print("Pausing mic")
            self.micButton.setColor(helper.colors_dict['red'])
            self.yourInterpreter.detector_paused = True
            self.micButton.setAccessibleDescription("Allows you to mute yourself. You are currently muted.")




    def speakerbutton_click(self):
        print("Clicked speaker button")
        if self.speakerButton.getColor() == helper.colors_dict['red']:
            # Already paused
            print("Unpausing speaker")
            self.speakerButton.setColor(self.speakerButton.getPreviousColor())
            self.theirInterpreter.synthetizer_paused = False
            self.micButton.setAccessibleDescription("Allows you to mute the other user. They are currently not muted.")
        else:
            # Not paused
            print("Pausing speaker")
            self.speakerButton.setColor(helper.colors_dict['red'])
            self.theirInterpreter.synthetizer_paused = True
            self.micButton.setAccessibleDescription("Allows you to mute the other user. They are currently muted.")


    def stop_clicked(self):
        if self.theirInterpreter.cloner is not None:
            if self.theirInterpreter.synthetizer.ttsVoice is not None:
                #We successfully cloned a voice. Update the voice list.
                newVoice = f"{self.theirInterpreter.synthetizer.ttsVoice.initialName} - {self.theirInterpreter.synthetizer.ttsVoice.voiceID}"
                self.layout.removeWidget(self.inactiveLayout)
                self.inactiveLayout = QWidget()
                self.inactiveLayout.setLayout(self.init_inactive_state())
                self.layout.addWidget(self.inactiveLayout)
                self.set_state("inactive")
                self.voiceType.button_clicked(1, self.on_reuse)

                allItems = [self.voicePicker.combo_box.itemText(i) for i in range(self.voicePicker.combo_box.count())]
                if newVoice in allItems:
                    self.voicePicker.combo_box.setCurrentIndex(allItems.index(newVoice))
                else:
                    self.voicePicker.combo_box.setCurrentIndex(0)
                self.adjustSize()

        self.yourInterpreter.detector_paused = False
        self.theirInterpreter.synthetizer_paused = False

        messageBox = QMessageBox()
        messageBox.setWindowTitle(helper.translate_ui_text("Stopping..."))
        messageBox.setText(helper.translate_ui_text("Stopping interpreters, please wait..."))
        messageBox.setStandardButtons(QMessageBox.StandardButton.NoButton)  # No buttons
        signalEmitter = SignalEmitter()
        signalEmitter.signal.connect(lambda: messageBox.done(0))

        def interpreter_shutdown():
            self.yourInterpreter.set_interrupts()
            self.theirInterpreter.set_interrupts()
            print("Exiting your interpreter...")
            self.yourInterpreter.stop_interpretation()
            print("Exiting their interpreter...")
            self.theirInterpreter.stop_interpretation()

            signalEmitter.signal.emit()

        shutdownThread = threading.Thread(target=interpreter_shutdown)
        shutdownThread.start()
        QTimer.singleShot(1, lambda: (messageBox.activateWindow(), messageBox.raise_()))
        messageBox.exec()
        print("Interpreter shutdown completed")

        if self.transcript is not None:
            #Flush it, close it, reopen it and write the finalized version
            self.transcript["file"].flush()
            fileName = self.transcript["file"].name
            self.transcript["file"].close()
            if "subtitles" in self.transcript:
                with open(fileName, "w") as fp:
                    fp.write(srt.compose(self.transcript["subtitles"], reindex=True))

        self.transcript = None
        self.set_state("inactive")
        self.adjustSize()

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

        if self.configDialog is None:
            self.configDialog = ConfigDialog()

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

def main():
    tracemalloc.start()
    app = QApplication([])

    app.setStyleSheet(helper.get_stylesheet())

    if "ui_language" not in settings:
        settings["ui_language"] = "System language - syslang"


    #These are the keys I expect the config to have.
    expectedKeys  = [
        "voice_recognition_type",
        "model_size",
        "transcription_storage",
        "ui_language",
        "audio_input_device",
        "audio_output_device",
        "your_ai_voice",
        "placeholder_ai_voice",
        "my_loudness_threshold",
        "my_pause_time"
    ]

    missing_keys = set(expectedKeys) - set(settings.keys())
    if len(missing_keys) > 0:
        firstTimeSetup.run_first_time_setup()


    dialog = MainWindow()
    dialog.show()
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
