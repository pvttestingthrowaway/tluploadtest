import copy
import os
import threading

import deepl as deepl
import elevenlabslib
import keyring as keyring
import openai
import websocket
from audoai.noise_removal import NoiseRemovalClient

from utils import helper
from utils.helper import settings

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QStyle, QStyleOptionSlider, QSlider, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QFileDialog, QLineEdit, QCheckBox

class LocalizedCheckbox(QCheckBox):
    def __init__(self, configKey, text=None, cacheSkip=False):
        super(LocalizedCheckbox, self).__init__(helper.translate_ui_text(text, settings["ui_language"], cacheSkip=cacheSkip))
        self.cacheSkip = cacheSkip
        self.configKey = configKey
        if configKey not in settings:
            settings[configKey] = False
        self.setChecked(settings[configKey])

    def setText(self, a0: str) -> None:
        super(LocalizedCheckbox, self).setText(helper.translate_ui_text(a0, settings["ui_language"], cacheSkip=self.cacheSkip))

    def get_value(self):
        return self.isChecked()


class LocalizedLabel(QLabel):
    def __init__(self, text=None, cacheSkip=False):
        super(LocalizedLabel, self).__init__(helper.translate_ui_text(text, settings["ui_language"], cacheSkip=cacheSkip))
        self.cacheSkip = cacheSkip

    def setText(self, a0: str) -> None:
        super(LocalizedLabel, self).setText(helper.translate_ui_text(a0, settings["ui_language"], cacheSkip=self.cacheSkip))

class LocalizedCenteredLabel(LocalizedLabel):
    def __init__(self, text=None, cacheSkip=False):
        super(LocalizedCenteredLabel, self).__init__(text, cacheSkip=cacheSkip)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

class CenteredLabel(QLabel):
    def __init__(self, text=None):
        super(CenteredLabel, self).__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

class InfoButton(QtWidgets.QPushButton):
    def __init__(self, info, isDir=False):
        super().__init__()

        self.setStyleSheet("background-color: transparent;")

        size_policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        size_policy.setHorizontalStretch(0)
        size_policy.setVerticalStretch(0)
        size_policy.setHeightForWidth(self.sizePolicy().hasHeightForWidth())
        self.setSizePolicy(size_policy)
        self.setMaximumWidth(30)  # adjust width as needed
        if isDir:
            self.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_DirHomeIcon))
        else:
            self.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxInformation))
            self.clicked.connect(lambda: self.show_info(helper.translate_ui_text(info, settings["ui_language"])))

    def show_info(self, info):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText(info)
        msgBox.exec()

class LabeledInput(QtWidgets.QWidget):
    def __init__(self, label, configKey, data=None, info=None, infoIsDir=False, protected=False, fixedComboBoxSize=30, localizeComboBox=False):
        super().__init__()
        self.configKey = configKey
        self.layout = QtWidgets.QVBoxLayout(self)
        self.label = LocalizedCenteredLabel(label)
        self.layout.addWidget(self.label)
        self.protected = protected
        self.line_edit = None
        self.combo_box = None

        self.input_widget = QtWidgets.QWidget()
        self.input_layout = QtWidgets.QHBoxLayout(self.input_widget)
        self.input_layout.setSpacing(10)  # adjust the space between widgets

        if isinstance(data, list):
            self.combo_box = QtWidgets.QComboBox()
            if fixedComboBoxSize is not None:
                self.combo_box.setMinimumContentsLength(fixedComboBoxSize)
                self.combo_box.setSizeAdjustPolicy(self.combo_box.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

            if localizeComboBox:
                data_translated = list()
                for item in data:
                    data_translated.append(helper.translate_ui_text(item,settings["ui_language"]))
                self.combo_box.addItems(data_translated)
            else:
                self.combo_box.addItems(data)

            self.input_layout.addWidget(self.combo_box)
        else:
            self.line_edit = QtWidgets.QLineEdit()
            self.line_edit.setText(data)
            if protected:
                self.line_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)

            self.input_layout.addWidget(self.line_edit)

        currentValue = None
        if protected:
            currentValue = keyring.get_password("polyecho", configKey)
        else:
            if configKey in settings:
                currentValue = settings[configKey]

        if currentValue is not None:
            if isinstance(data, list):
                allItems = [self.combo_box.itemText(i) for i in range(self.combo_box.count())]
                if currentValue in allItems:
                    self.combo_box.setCurrentIndex(allItems.index(currentValue))
                else:
                    self.combo_box.setCurrentIndex(0)
            else:
                self.line_edit.setText(currentValue)

        self.layout.addWidget(self.input_widget)

        if info is not None:
            self.info_button = InfoButton(info, infoIsDir)
            self.input_layout.addWidget(self.info_button)
            if infoIsDir:
                self.info_button.clicked.connect(self.select_file)

    def select_file(self):
        self.line_edit.setText(str(QFileDialog.getExistingDirectory(self, "Select Directory")))

    def get_value(self):
        if self.line_edit is not None:
            return self.line_edit.text()
        else:
            return self.combo_box.currentText()

class ToggleButton(QtWidgets.QWidget):
    def __init__(self, label, button_texts, callbacks, configKey, info=None):
        super().__init__()

        for index, text in enumerate(button_texts):
            button_texts[index] = helper.translate_ui_text(text, settings["ui_language"])

        self.layout = QtWidgets.QGridLayout(self)
        self.selected_button = 0  # add an instance variable to track selected button

        self.label = LocalizedCenteredLabel(label)
        self.layout.addWidget(self.label, 0, 0, 1, 2)  # add to the top

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout(self.button_widget)
        self.button_layout.setSpacing(0)  # adjust the space between buttons

        self.button1 = QtWidgets.QPushButton(button_texts[0])
        self.button1.clicked.connect(lambda: self.button_clicked(0, callbacks[0]))

        self.button2 = QtWidgets.QPushButton(button_texts[1])
        self.button2.clicked.connect(lambda: self.button_clicked(1, callbacks[1]))

        self.button_layout.addWidget(self.button1)
        self.button_layout.addWidget(self.button2)
        self.lower_layout = QHBoxLayout()
        self.lower_layout.addWidget(self.button_widget)
        self.lower_layout.setSpacing(0)

        self.layout.addLayout(self.lower_layout, 1, 0, 1, 2)
        self.configKey = configKey

        if configKey in settings:
            if isinstance(settings[configKey],int):
                self.button_clicked(settings[configKey], callbacks[settings[configKey]])
            else:
                if settings[configKey] == button_texts[1]:
                    self.button_clicked(1, callbacks[1])
                else:
                    self.button_clicked(0, callbacks[0])
        else:
            self.button_clicked(0, callbacks[0])

        if info is not None:
            self.info_button = InfoButton(info)
            self.lower_layout.addWidget(self.info_button)

    def show_info(self, info):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText(info)
        msgBox.exec()

    def button_clicked(self, button_index, callback):
        self.selected_button = button_index  # update the selected button index
        self.button1.setStyleSheet('' if button_index else 'background-color: yellow')
        self.button2.setStyleSheet('background-color: yellow' if button_index else '')
        callback()

    def get_value(self):
        return self.selected_button

#Code taken from https://gist.github.com/wiccy46/b7d8a1d57626a4ea40b19c5dbc5029ff
class LabeledSlider(QWidget):
    def __init__(self, minimum, maximum, configKey, interval=1, orientation=Qt.Orientation.Horizontal,
                 labels=None, defaultPosition=0, parent=None):
        super(LabeledSlider, self).__init__(parent=parent)

        levels=range(minimum, maximum + interval, interval)
        self.labels = labels
        self.configKey = configKey
        if labels is not None:
            if not isinstance(labels, (tuple, list)):
                raise Exception("<labels> is a list or tuple.")
            if len(labels) != len(levels):
                raise Exception("Size of <labels> doesn't match levels.")
            self.levels=list(zip(levels,labels))
        else:
            self.levels=list(zip(levels,map(str,levels)))

        if orientation==Qt.Orientation.Horizontal:
            self.layout=QVBoxLayout(self)
        elif orientation==Qt.Orientation.Vertical:
            self.layout=QHBoxLayout(self)
        else:
            raise Exception("<orientation> wrong.")

        # gives some space to print labels
        self.left_margin=10
        self.top_margin=10
        self.right_margin=10
        self.bottom_margin=10

        self.layout.setContentsMargins(self.left_margin,self.top_margin,
                self.right_margin,self.bottom_margin)

        self.sl=QSlider(orientation, self)
        self.sl.setMinimum(minimum)
        self.sl.setMaximum(maximum)
        self.sl.setValue(minimum)
        self.sl.setSliderPosition(defaultPosition)
        if orientation==Qt.Orientation.Horizontal:
            self.sl.setTickPosition(QSlider.TickPosition.TicksBelow)
            self.sl.setMinimumWidth(300) # just to make it easier to read
        else:
            self.sl.setTickPosition(QSlider.TickPosition.TicksLeft)
            self.sl.setMinimumHeight(300) # just to make it easier to read
        self.sl.setTickInterval(interval)
        self.sl.setSingleStep(1)

        self.sl.valueChanged.connect(self.on_value_changed)

        self.layout.addWidget(self.sl)
        self.layout.addWidget(LocalizedLabel("VRAM usage:"))

    def paintEvent(self, e):

        super(LabeledSlider,self).paintEvent(e)
        style=self.sl.style()
        painter=QPainter(self)
        st_slider=QStyleOptionSlider()
        st_slider.initFrom(self.sl)
        st_slider.orientation=self.sl.orientation()
        length=style.pixelMetric(QStyle.PixelMetric.PM_SliderLength, st_slider, self.sl)
        available=style.pixelMetric(QStyle.PixelMetric.PM_SliderSpaceAvailable, st_slider, self.sl)

        for v, v_str in self.levels:

            # get the size of the label

            rect=painter.drawText(QRect(), Qt.TextFlag.TextDontPrint, v_str)

            if self.sl.orientation()==Qt.Orientation.Horizontal:
                # I assume the offset is half the length of slider, therefore
                # + length//2
                x_loc=QStyle.sliderPositionFromValue(self.sl.minimum(),
                        self.sl.maximum(), v, available)+length//2

                # left bound of the text = center - half of text width + L_margin
                left=x_loc-rect.width()//2+self.left_margin
                bottom=self.rect().bottom()

                # enlarge margins if clipping
                if v==self.sl.minimum():
                    if left<=0:
                        self.left_margin=rect.width()//2-x_loc
                    if self.bottom_margin<=rect.height():
                        self.bottom_margin=rect.height()

                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

                if v==self.sl.maximum() and rect.width()//2>=self.right_margin:
                    self.right_margin=rect.width()//2
                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

            else:
                y_loc=QStyle.sliderPositionFromValue(self.sl.minimum(),
                        self.sl.maximum(), v, available, upsideDown=True)

                bottom=y_loc+length//2+rect.height()//2+self.top_margin-3
                # there is a 3 px offset that I can't attribute to any metric

                left=self.left_margin-rect.width()
                if left<=0:
                    self.left_margin=rect.width()+2
                    self.layout.setContentsMargins(self.left_margin,
                            self.top_margin, self.right_margin,
                            self.bottom_margin)

            pos=QPoint(left, bottom)
            painter.drawText(pos, v_str)

        return

    def get_value(self):
        return self.sl.value()

    def on_value_changed(self, value):
        if self.labels is not None:
            labelValue = self.labels[value]
            print(f"Slider label: {labelValue}")
        return


#Code taken from https://stackoverflow.com/questions/54914188/has-anyone-implemented-a-way-to-move-selected-items-from-one-list-view-box-to-an
class TwoListSelection(QtWidgets.QWidget):
    def __init__(self, configKey, parent=None):
        super(TwoListSelection, self).__init__(parent)
        self.configKey = configKey
        self.setup_layout()
    def setup_layout(self):
        self.layout = QtWidgets.QGridLayout(self)

        self.availableList = QtWidgets.QListWidget()
        self.selectedList = QtWidgets.QListWidget()

        self.mBtnMoveToAvailable = QtWidgets.QPushButton(">")
        self.mBtnMoveToSelected = QtWidgets.QPushButton("<")
        self.mButtonToAvailable = QtWidgets.QPushButton("<<")

        input_label = LocalizedCenteredLabel("Available languages")
        output_label = LocalizedCenteredLabel("Selected languages")

        self.layout.addWidget(input_label, 0, 0)

        self.layout.addWidget(self.availableList, 1, 0, 3, 1)

        vlay = QtWidgets.QVBoxLayout()
        vlay.addWidget(self.mBtnMoveToAvailable)
        vlay.addWidget(self.mBtnMoveToSelected)
        vlay.addWidget(self.mButtonToAvailable)
        self.layout.addLayout(vlay, 1, 1, 3, 1)

        self.layout.addWidget(output_label, 0, 2)
        self.layout.addWidget(self.selectedList, 1, 2, 3, 1)

        self.update_buttons_status()
        self.connections()
    @QtCore.pyqtSlot()
    def update_buttons_status(self):
        self.mBtnMoveToAvailable.setDisabled(not bool(self.availableList.selectedItems()) or self.selectedList.currentRow() == 0 or len(self.get_right_elements()) >= 10)
        self.mBtnMoveToSelected.setDisabled(not bool(self.selectedList.selectedItems()))

    def connections(self):
        #TODO: Hook these functions to update the settings dict.
        self.availableList.itemSelectionChanged.connect(self.update_buttons_status)
        self.selectedList.itemSelectionChanged.connect(self.update_buttons_status)
        self.mBtnMoveToAvailable.clicked.connect(self.on_mBtnMoveToAvailable_clicked)
        self.mBtnMoveToSelected.clicked.connect(self.on_mBtnMoveToSelected_clicked)
        self.mButtonToAvailable.clicked.connect(self.on_mButtonToAvailable_clicked)

    @QtCore.pyqtSlot()
    def on_mBtnMoveToAvailable_clicked(self):
        self.selectedList.addItem(self.availableList.takeItem(self.availableList.currentRow()))
        self.update_buttons_status()
        self.updateConfigItems()

    @QtCore.pyqtSlot()
    def on_mBtnMoveToSelected_clicked(self):
        self.availableList.addItem(self.selectedList.takeItem(self.selectedList.currentRow()))
        self.update_buttons_status()
        self.updateConfigItems()

    @QtCore.pyqtSlot()
    def on_mButtonToAvailable_clicked(self):
        while self.selectedList.count() > 0:
            self.availableList.addItem(self.selectedList.takeItem(0))
        self.update_buttons_status()
        self.updateConfigItems()

    def updateConfigItems(self):
        print(self.get_right_elements())
        settings[self.configKey] = self.get_right_elements()

    @QtCore.pyqtSlot()
    def on_mBtnUp_clicked(self):
        row = self.selectedList.currentRow()
        currentItem = self.selectedList.takeItem(row)
        self.selectedList.insertItem(row - 1, currentItem)
        self.selectedList.setCurrentRow(row - 1)

    @QtCore.pyqtSlot()
    def on_mBtnDown_clicked(self):
        row = self.selectedList.currentRow()
        currentItem = self.selectedList.takeItem(row)
        self.selectedList.insertItem(row + 1, currentItem)
        self.selectedList.setCurrentRow(row + 1)

    def addAvailableItems(self, items):
        self.availableList.addItems(items)

    def addSelectedItems(self, items):

        for item in items:
            itemExists = False
            items_list = self.availableList.findItems(item, Qt.MatchFlag.MatchExactly)
            for listItem in items_list:
                self.availableList.takeItem(self.availableList.row(listItem))
                itemExists = True
            if itemExists:
                self.selectedList.addItem(item)

    def get_left_elements(self):
        r = []
        for i in range(self.availableList.count()):
            it = self.availableList.item(i)
            r.append(it.text())
        return r

    def get_right_elements(self):
        r = []
        for i in range(self.selectedList.count()):
            it = self.selectedList.item(i)
            r.append(it.text())
        return r

class SpeechRecWidget(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)

        self.myEnergyThreshold = LabeledInput(
            "My loudness threshold",
            configKey="my_loudness_threshold",
            data="250"
        )
        self.layout.addWidget(self.myEnergyThreshold, 0, 0)

        #self.dynamicLoudness = LocalizedCheckbox(configKey="dynamic_loudness",text="Dynamic loudness threshold")
        #self.layout.addWidget(self.dynamicLoudness, 0, 1)

        self.myPauseTime = LabeledInput(
            "My pause time (in seconds)",
            data="0.5",
            configKey="my_pause_time"
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

    def on_change(self, text):
        print(f"Selected option: {text}")

class LocalWidgets(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)

        self.VRAMlabel = LocalizedCenteredLabel(cacheSkip=True)
        self.update_memory_label()
        labels = ["1 GB", "2 GB", "3 GB", "5 GB"]
        self.slider = LabeledSlider(minimum=0, maximum=3,labels=labels, defaultPosition=2, configKey="model_size")
        self.layout.addWidget(LocalizedLabel("Fast"),0,0,1,1)
        self.layout.addWidget(self.slider, 0, 1, 2, 1)
        self.layout.addWidget(LocalizedLabel("Accurate"),0,2,1,1)

        self.layout.addWidget(self.VRAMlabel, 2, 0, 1, 3)  # add to the bottom

        #for i in range(3):
            #self.layout.setColumnStretch(i, 1)

    def update_memory_label(self):
        return
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

    def on_change(self, text):
        print("New openAI API Key: " + text)


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

    def on_change(self, text):
        print(f"Selected option: {text}")

class ConfigDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()

        user = None
        apiKey = keyring.get_password("polyecho", "elevenlabs_api_key")
        if apiKey is not None:
            try:
                user = elevenlabslib.ElevenLabsUser(apiKey)
            except ValueError:
                pass
        currentRow = 0
        self.layout = QtWidgets.QGridLayout(self)

        self.input_device = LabeledInput(
            "Audio input device",
            configKey = "audio_input_device",
            data=helper.get_list_of_portaudio_devices("input")
        )
        self.layout.addWidget(self.input_device, currentRow, 0)

        self.output_device = LabeledInput(
            "Audio output device",
            configKey="audio_output_device",
            data = helper.get_list_of_portaudio_devices("output")
        )
        self.layout.addWidget(self.output_device, currentRow, 2)

        currentRow += 1

        self.deepl_api_key = LabeledInput(
            "DeepL API Key (Optional)",
            configKey="deepl_api_key",
            protected=True,
            info="Optional. If the language is not supported by DeepL (or an API key is not provided) Google Translate will be used instead."
        )
        self.layout.addWidget(self.deepl_api_key, currentRow, 0)

        self.audo_api_key = LabeledInput(
            "Audo API Key (Optional)",
            configKey="audo_api_key",
            protected=True,
            info="Optional, enhances the audio for clone creation."
        )
        self.layout.addWidget(self.audo_api_key, currentRow, 2)

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
            "Your AI Voice",
            configKey="your_ai_voice",
            data=helper.get_list_of_voices(user)
        )
        self.layout.addWidget(self.your_ai_voice, currentRow, 0)

        self.placeholder_ai_voice = LabeledInput(
            "Placeholder AI Voice",
            configKey="placeholder_ai_voice",
            data=helper.get_list_of_voices(user)
        )
        self.layout.addWidget(self.placeholder_ai_voice, currentRow, 2)

        currentRow += 1

        self.transcript_save_location = LabeledInput(
            "Transcript save location",
            configKey="transcript_save_location",
            info="This is where transcripts will be saved.",
            infoIsDir=True
        )
        self.layout.addWidget(self.transcript_save_location, currentRow, 2)


        self.transcription_storage = ToggleButton(
            "Transcription storage",
            ["Enable", "Disable"],
            [self.on_enable, self.on_disable],
            info="TRANSCRIPTSTORAGEINFO",
            configKey="transcription_storage"
        )
        self.layout.addWidget(self.transcription_storage, currentRow, 0)

        self.transcript_save_location.setVisible(self.transcription_storage.get_value() == 0)



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
            info="This is the type of voice recognition.",
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

        saveButton = QtWidgets.QPushButton(helper.translate_ui_text("Save", settings["ui_language"]))
        saveButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        saveButton.setMinimumSize(30, 25)  # adjust the size as per your need
        saveButton.clicked.connect(self.save_clicked)
        buttonLayout.addWidget(saveButton)

        cancelButton = QtWidgets.QPushButton(helper.translate_ui_text("Cancel", settings["ui_language"]))
        cancelButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        cancelButton.setMinimumSize(30, 25)  # adjust the size as per your need
        cancelButton.clicked.connect(self.cancel_clicked)
        buttonLayout.addWidget(cancelButton)
        wrapperLayout = QtWidgets.QVBoxLayout()
        wrapperLayout.addStretch()
        wrapperLayout.addLayout(buttonLayout)
        # add the button layout to the grid layout
        self.layout.addLayout(wrapperLayout, currentRow, 2)

        self.ui_language = LabeledInput(
            "GUI Language",
            configKey="ui_language",
            data=helper.get_googletrans_native_langnames(settings["ui_language"])
        )

        self.layout.addWidget(self.ui_language, currentRow, 0, 1, 1)

        for i in range(3):
            self.layout.setColumnStretch(i, 1)

        for i in range(currentRow+1):
            self.layout.setRowStretch(i, 1)

        self.adjustSize()
        #recursive_set_start_value(self.layout, QtWidgets.QLabel, 'Default Text')

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
                        try:
                            user = elevenlabslib.ElevenLabsUser(value)
                            if not user.get_voice_clone_available():
                                msgBox = QtWidgets.QMessageBox()
                                msgBox.setText(helper.translate_ui_text("Your ElevenLabs subscription does not support voice cloning. \nSome features won't be available.", settings["ui_language"]))
                                msgBox.exec()
                        except ValueError:
                            errorMessage += "\nElevenLabs API error. API Key may be incorrect."

                if configKey == "openai_api_key":
                    if self.voice_recognition_type.get_value() == 1:
                        if recognitionModeChanged or keyring.get_password("polyecho","openai_api_key") != value:
                            openai.api_key = value
                            try:
                                openai.Model.list()
                            except openai.error.AuthenticationError:
                                errorMessage += "\nOpenAI API error. API Key may be incorrect."

                if configKey == "deepl_api_key" and value != "":
                    if keyring.get_password("polyecho","deepl_api_key") != value:
                        deeplTranslator = deepl.Translator(value).set_app_info("polyecho", "1.0.0")
                        try:
                            deeplTranslator.get_usage()
                        except deepl.AuthorizationException:
                            errorMessage += "\nDeepL API error. API Key may be incorrect."

                if configKey == "audo_api_key" and value != "":
                    if keyring.get_password("polyecho", "audo_api_key") != value:
                        audoClient = NoiseRemovalClient(value)
                        try:
                            socket = audoClient.connect_websocket("TestID")
                            socket.close()
                        except websocket.WebSocketBadStatusException:
                            errorMessage += "\nAudo API error. API Key may be incorrect."

                if configKey == "transcript_save_location":
                    if self.transcription_storage.get_value() == 0:
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
            msgBox.setText(helper.translate_ui_text(errorMessage, settings["ui_language"]))
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
    def on_enable(self):
        print("Transcription storage enabled.")
        self.transcript_save_location.setVisible(True)

    def on_disable(self):
        print("Transcription storage disabled.")
        self.transcript_save_location.setVisible(False)

    def on_local(self):
        self.localWhisperWidgets.setVisible(True)
        self.localWhisperWidgets.update_memory_label()
        #self.online_provider.setVisible(False)
        #self.azureWidgets.setVisible(False)
        self.whisperAPIWidgets.setVisible(False)
        self.localWhisperWidgets.layout.addWidget(self.speechRecWidgets, 3, 0, 2, 3)
        self.adjustSize()

    def on_online(self):
        #self.online_provider.setVisible(True)
        self.localWhisperWidgets.setVisible(False)
        #self.adjustSize()

        #if self.online_provider.get_selected_button() == 0:
        self.on_whisper()
        #else:
        #    self.on_azure()


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

    dialog = ConfigDialog()
    dialog.show()

    app.exec()

if __name__ == "__main__":
    main()
