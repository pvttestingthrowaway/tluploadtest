import datetime
import json
import os
from typing import Optional, TextIO

import elevenlabslib
import keyring

from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QGridLayout, QPushButton, QWidget, QSizePolicy, QMessageBox

from utils import helper
from configWindow import LabeledInput, ConfigDialog, ToggleButton, default_settings, CenteredLabel, LocalizedCenteredLabel, settings
from utils.helper import get_supported_languages, get_supported_languages_localized
from interpreter import Interpreter

greenColor = "green"
yellowColor = "yellow"
redColor = "red"

class ResizableCircularButton(QPushButton):
    def __init__(self, bgColor, icon=None, *args, **kwargs):
        super(ResizableCircularButton, self).__init__(*args, **kwargs)
        self.bgColor = bgColor
        self.previousColor = bgColor
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHeightForWidth(True)
        self.setSizePolicy(sizePolicy)
        if icon is not None:
            self.setIcon(icon)

    def heightForWidth(self, width):
        return width

    def setColor(self, bgColor):
        self.previousColor = self.bgColor
        self.bgColor = bgColor
        size = min(self.width(), self.height())
        self.setStyleSheet(f"border-radius : {int(size / 2)}; background-color: {self.bgColor};")

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
        self.wrapper = QWidget()
        self.layout.addWidget(self.wrapper)
        self.wrapper.setLayout(self.init_inactive_state())

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

        # Create rectangular button
        stop_button = QPushButton(helper.translate_ui_text("Stop", settings["ui_language"]))
        stop_button.clicked.connect(self.stop_clicked)

        # Set active layout
        active_layout.addWidget(self.activeLabels["me"]["recognized"], 0, 0)
        active_layout.addWidget(self.activeLabels["them"]["recognized"], 0, 2)
        active_layout.addWidget(self.micButton, 1, 0)

        active_layout.addWidget(self.speakerButton, 1, 2)
        active_layout.addWidget(self.activeLabels["me"]["translated"], 2, 0)
        active_layout.addWidget(self.activeLabels["them"]["translated"], 2, 2)
        active_layout.addWidget(stop_button, 3, 1)
        active_layout.addWidget(self.activeLabels["cloneProgress"], 3, 2)

        for i in range(3):
            active_layout.setColumnStretch(i, 1)

        for i in range(4):
            active_layout.setRowStretch(i, 1)

        self.wrapper.setLayout(active_layout)
        return active_layout

    def init_inactive_state(self) -> QGridLayout:
        # Initialize layout
        inactive_layout = QtWidgets.QGridLayout(self)

        self.user = None
        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        if apiKey is not None:
            try:
                self.user:elevenlabslib.ElevenLabsUser = elevenlabslib.ElevenLabsUser(apiKey)
            except ValueError:
                pass

        # First row
        self.your_output_lang = LabeledInput(
            "Your output language",
            configKey = "your_output_language",
            data=get_supported_languages_localized(self.user, settings["ui_language"]),
            fixedComboBoxSize=None
        )
        inactive_layout.addWidget(self.your_output_lang, 0, 0)

        self.their_output_lang = LabeledInput(
            "Their output language",
            configKey="their_output_language",
            data = get_supported_languages_localized(self.user, settings["ui_language"]),
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
                [self.on_reuse, self.on_create_new],
                configKey="output_voice"
            )
            inactive_layout.addWidget(self.voiceType, 1, 1)
        else:
            self.nameInput.setVisible(False)
            self.voicePicker.setVisible(True)


        # Third row
        settings_button = QPushButton(helper.translate_ui_text("Settings", settings["ui_language"]))
        settings_button.clicked.connect(self.show_settings)  # connect to method
        inactive_layout.addWidget(settings_button, 3, 0)

        start_button = QtWidgets.QPushButton(helper.translate_ui_text("Start", settings["ui_language"]))
        start_button.setStyleSheet("background-color: green")
        start_button.clicked.connect(self.start_clicked)  # connect to method
        inactive_layout.addWidget(start_button, 3, 2)

        if self.user is None:
            start_button.setEnabled(False)

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
            cloneNew = self.voiceType.get_selected_button() == 0

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


        if os.path.exists("config.json"):
            with open("config.json", "r") as fp:
                settings = json.load(fp)
        else:
            settings = default_settings
        settings["your_output_language"] = self.your_output_lang.combo_box.currentText()
        settings["their_output_language"] = self.their_output_lang.combo_box.currentText()
        with open("config.json", "w") as fp:
            json.dump(settings, fp, indent=4)


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


        self.clearLayout()
        self.wrapper.setLayout(self.init_active_state())




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
        self.myInterpreter = Interpreter(settings["audio_input_device"], myVirtualOutput, settings, settings["your_output_language"], settings["your_ai_voice"])

        #TODO: TEST THIS.
        if cloneNew:
            self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], voiceIDOrName=self.nameInput.line_edit.text(), createNewVoice=True)
            self.theirInterpreter.cloneProgressSignal.connect(lambda cloneProgress: self.setCloneProgress(cloneProgress))
            self.speakerButton.setColor(yellowColor)
        else:
            self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], voiceIDOrName=self.voicePicker.combo_box.currentText())
            self.speakerButton.setColor(greenColor)

        #TODO: remove this because it was only for testing
        theirVirtualInput = "Headset (3- GSA 70 Communication Audio) - 1"
        self.theirInterpreter = Interpreter(theirVirtualInput, settings["audio_output_device"], settings, settings["their_output_language"], settings["placeholder_ai_voice"])

        self.myInterpreter.textReadySignal.connect(lambda recognizedText, translatedText: self.setSpeechLabelsText("me", recognizedText, translatedText))
        self.theirInterpreter.textReadySignal.connect(lambda recognizedText, translatedText: self.setSpeechLabelsText("them", recognizedText, translatedText))

        self.micButton.clicked.connect(self.micbutton_click)
        self.speakerButton.clicked.connect(self.speakerbutton_click)

        if settings["transcription_storage"]:
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
        self.activeLabels[who]["recognized"].setText(recognizedText)
        self.activeLabels[who]["translated"].setText(translatedText)

        if self.transcript is not None:
            identifier = f"{who[0].upper() + who[1:]}@{datetime.datetime.now().strftime('%H:%M:%S')}"
            self.transcript.write(f"{identifier} (Original) - {recognizedText}\n")
            self.transcript.write(f"{identifier} (Translated) - {translatedText}\n\n")
            self.transcript.flush()


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
        self.transcript.flush()
        self.transcript = None
        self.clearLayout()
        self.wrapper.setLayout(self.init_inactive_state())



    def clearLayout(self):
        self.layout.removeWidget(self.wrapper)
        self.wrapper = QWidget()
        self.layout.addWidget(self.wrapper)
    def on_reuse(self):
        self.nameInput.setVisible(True)
        self.voicePicker.setVisible(False)
    def on_create_new(self):
        self.nameInput.setVisible(False)
        self.voicePicker.setVisible(True)

    def show_settings(self):
        newConfigDialog = ConfigDialog()
        newConfigDialog.exec()

        self.clearLayout()
        self.wrapper.setLayout(self.init_inactive_state())


def main():
    app = QApplication([])
    dialog = MainWindow()
    dialog.show()


    app.exec()

    if os.path.exists("config.json"):
        with open("config.json", "r") as fp:
            settings = json.load(fp)
    else:
        settings = default_settings
    try:
        settings["your_output_language"] = dialog.your_output_lang.combo_box.currentText()
        settings["their_output_language"] = dialog.their_output_lang.combo_box.currentText()
        with open("config.json", "w") as fp:
            json.dump(settings, fp, indent=4)
    except RuntimeError:
        pass

if __name__ == '__main__':
    main()
