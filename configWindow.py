import deepl as deepl
import elevenlabslib
import keyring as keyring
import openai
import websocket
from audoai.noise_removal import NoiseRemovalClient

from utils.helper import *

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtCore import QPoint, QRect, Qt
from PyQt6.QtGui import QPainter
from PyQt6.QtWidgets import QStyle, QStyleOptionSlider, QSlider, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QFileDialog, QLineEdit

default_settings = {
    "voice_recognition_type": "Local",
    "model_size": "medium",
    "transcription_storage": "Disable",
    "deepl_api_key": "",
    "dynamic_loudness_threshold": True
}

if os.path.exists("config.json"):
    with open("config.json","r") as fp:
        settings = json.load(fp)
else:
    settings = default_settings
    with open("config.json", "w") as fp:
        json.dump(settings, fp, indent=4)

class LocalizedCenteredLabel(QLabel):
    def __init__(self, text=None, cacheSkip=False):
        super(LocalizedCenteredLabel, self).__init__(translate_ui_text(text, settings["ui_language"], cacheSkip=cacheSkip))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cacheSkip = cacheSkip

    def setText(self, a0: str) -> None:
        super(LocalizedCenteredLabel, self).setText(translate_ui_text(a0, settings["ui_language"], cacheSkip=self.cacheSkip))
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
            self.clicked.connect(lambda: self.show_info(translate_ui_text(info, settings["ui_language"])))

    def show_info(self, info):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText(info)
        msgBox.exec()

class LabeledInput(QtWidgets.QWidget):
    def __init__(self, label, configKey, data=None, info=None, infoIsDir=False, maskText=False, fixedComboBoxSize=30, localizeComboBox=False):
        super().__init__()

        self.layout = QtWidgets.QVBoxLayout(self)
        self.label = LocalizedCenteredLabel(label)
        self.layout.addWidget(self.label)

        self.input_widget = QtWidgets.QWidget()
        self.input_layout = QtWidgets.QHBoxLayout(self.input_widget)
        self.input_layout.setSpacing(10)  # adjust the space between widgets

        def updateConfigKey(text):
            if maskText:
                settings["keyring_"+configKey] = text
            else:
                settings[configKey] = text

        if isinstance(data, list):
            self.combo_box = QtWidgets.QComboBox()
            if fixedComboBoxSize is not None:
                self.combo_box.setMinimumContentsLength(fixedComboBoxSize)
                self.combo_box.setSizeAdjustPolicy(self.combo_box.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)

            if localizeComboBox:
                data_translated = list()
                for item in data:
                    data_translated.append(translate_ui_text(item,settings["ui_language"]))
                self.combo_box.addItems(data_translated)
            else:
                self.combo_box.addItems(data)

            self.combo_box.currentTextChanged[str].connect(updateConfigKey)

            self.input_layout.addWidget(self.combo_box)
        else:
            self.line_edit = QtWidgets.QLineEdit()
            self.line_edit.setText(data)
            if maskText:
                self.line_edit.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
            self.line_edit.editingFinished.connect(lambda: updateConfigKey(self.line_edit.text()))

            self.input_layout.addWidget(self.line_edit)

        currentValue = None
        if maskText:
            currentValue = keyring.get_password("polyecho", configKey)
            settings["keyring_"+configKey] = currentValue
        else:
            if configKey in settings:
                currentValue = settings[configKey]
            else:
                if isinstance(data, list) and len(data) > 0:
                    settings[configKey] = data[0]
                else:
                    settings[configKey] = data

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

class ToggleButton(QtWidgets.QWidget):
    def __init__(self, label, button_texts, callbacks, configKey, info=None):
        super().__init__()

        for index, text in enumerate(button_texts):
            button_texts[index] = translate_ui_text(text, settings["ui_language"])

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
            if settings[configKey] == button_texts[1]:
                self.button_clicked(1, callbacks[1])
            else:
                self.button_clicked(0, callbacks[0])
        else:
            self.button_clicked(0, callbacks[0])
            settings[configKey] = button_texts[0]

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
        settings[self.configKey] = self.button2.text() if button_index else self.button1.text()
        callback()

    def get_selected_button(self):
        return self.selected_button

#Code taken from https://gist.github.com/wiccy46/b7d8a1d57626a4ea40b19c5dbc5029ff
class LabeledSlider(QWidget):
    def __init__(self, minimum, maximum, configKey, interval=1, orientation=Qt.Orientation.Horizontal,
                 labels=None, realValues=None, defaultPosition=0, parent=None):
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

        if realValues is not None:
            assert(len(realValues) == len(levels))
        self.realValues = realValues

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
        if self.realValues is not None:
            self.sl.setSliderPosition(self.realValues.index(defaultPosition))
        else:
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
        self.layout.addWidget(QtWidgets.QLabel(translate_ui_text("VRAM usage:", settings["ui_language"])))

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

    def on_value_changed(self, value):
        if self.labels is not None:
            labelValue = self.labels[value]
            print(f"Slider label: {labelValue}")
        if self.realValues is not None:
            settings[self.configKey] = self.realValues[value]
        else:
            settings[self.configKey] = value
        print(f"Slider value: {settings[self.configKey]}")
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

        for i in range(3):
            self.layout.setColumnStretch(i, 1)

        self.energyThreshold = LabeledInput(
            "Loudness threshold",
            configKey="loudness_threshold",
            data="250"
        )
        self.layout.addWidget(self.energyThreshold, 0, 0)

        self.dynamicLoudness = QtWidgets.QCheckBox(translate_ui_text("Dynamic loudness threshold", settings["ui_language"]))
        dynamicLoudnessKey = self.dynamicLoudness.text().lower().replace(" ","_")
        if dynamicLoudnessKey in settings:
            self.dynamicLoudness.setChecked(bool(settings[dynamicLoudnessKey]))
        else:
            settings[dynamicLoudnessKey] = False
        self.dynamicLoudness.stateChanged.connect(self.on_checkbox_state_changed)
        self.layout.addWidget(self.dynamicLoudness, 0, 1)

        self.pauseTime = LabeledInput(
            "Pause time (in seconds)",
            data="0.5",
            configKey="pause_time"
        )
        self.layout.addWidget(self.pauseTime, 0, 2)

    def on_change(self, text):
        print(f"Selected option: {text}")

    def on_checkbox_state_changed(self, state):
        configKey:str = self.sender().text().lower().replace(" ","_")
        settings[configKey] = self.sender().isChecked()
        if self.sender().isChecked():
            print("Checkbox is checked")
        else:
            print("Checkbox is not checked")

class LocalWidgets(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QtWidgets.QGridLayout(self)

        self.VRAMlabel = LocalizedCenteredLabel(cacheSkip=True)
        self.update_memory_label()
        labels = ["1 GB", "2 GB", "3 GB", "5 GB"]
        default_value = 2
        if "model_size" in settings:
            default_value = settings["model_size"]
        else:
            settings["model_size"] = default_value

        self.slider = LabeledSlider(minimum=0, maximum=3,labels=labels, realValues=["base", "small", "medium","large-v2"], defaultPosition=default_value, configKey="model_size")
        self.layout.addWidget(QtWidgets.QLabel(translate_ui_text("Fast", settings["ui_language"])),0,0,1,1)
        self.layout.addWidget(self.slider, 0, 1, 2, 1)
        self.layout.addWidget(QtWidgets.QLabel(translate_ui_text("Accurate", settings["ui_language"])),0,2,1,1)

        self.layout.addWidget(self.VRAMlabel, 2, 0, 1, 3)  # add to the bottom

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
            maskText=True
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
            maskText=True,
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
        else:
            settings[configKey] = []

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
            data=get_list_of_portaudio_devices("input")
        )
        self.layout.addWidget(self.input_device, currentRow, 0)

        self.output_device = LabeledInput(
            "Audio output device",
            configKey="audio_input_device",
            data = get_list_of_portaudio_devices("output")
        )
        self.layout.addWidget(self.output_device, currentRow, 2)

        currentRow += 1

        self.deepl_api_key = LabeledInput(
            "DeepL API Key (Optional)",
            configKey="deepl_api_key",
            maskText=True,
            info="Optional. If the language is not supported by DeepL (or an API key is not provided) Google Translate will be used instead."
        )
        self.layout.addWidget(self.deepl_api_key, currentRow, 0)

        self.audo_api_key = LabeledInput(
            "Audo API Key (Optional)",
            configKey="audo_api_key",
            maskText=True,
            info="Optional, enhances the audio for clone creation."
        )
        self.layout.addWidget(self.audo_api_key, currentRow, 2)

        currentRow += 1

        self.elevenlabs_api_key = LabeledInput(
            "ElevenLabs API Key",
            configKey="elevenlabs_api_key",
            info="You can find your API Key under your Profile, on the website.",
            maskText=True
        )

        self.layout.addWidget(self.elevenlabs_api_key, currentRow, 0)

        currentRow += 1

        self.your_ai_voice = LabeledInput(
            "Your AI Voice",
            configKey="your_ai_voice",
            data=get_list_of_voices(user)
        )
        self.layout.addWidget(self.your_ai_voice, currentRow, 0)

        self.placeholder_ai_voice = LabeledInput(
            "Placeholder AI Voice",
            configKey="placeholder_ai_voice",
            data=get_list_of_voices(user)
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

        self.transcript_save_location.setVisible(self.transcription_storage.get_selected_button() == 0)



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

        self.layout.addWidget(self.whisperAPIWidgets, currentRow, 0, 3, 3)
        self.layout.addWidget(self.localWhisperWidgets, currentRow, 0, 3, 3)

        currentRow += 3

        # Save and Cancel buttons
        buttonLayout = QtWidgets.QHBoxLayout()

        saveButton = QtWidgets.QPushButton("Save")
        saveButton.setSizePolicy(QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum)
        saveButton.setMinimumSize(30, 25)  # adjust the size as per your need
        saveButton.clicked.connect(self.save_clicked)
        buttonLayout.addWidget(saveButton)

        cancelButton = QtWidgets.QPushButton("Cancel")
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
            data=get_googletrans_native_langnames()
        )

        self.layout.addWidget(self.ui_language, currentRow, 0, 1, 1)

        for i in range(3):
            self.layout.setColumnStretch(i, 1)

        for i in range(currentRow+1):
            self.layout.setRowStretch(i, 1)

        self.adjustSize()
        #recursive_set_start_value(self.layout, QtWidgets.QLabel, 'Default Text')

    def save_clicked(self):
        errorMessage = ""

        tl_cache_prep(settings["ui_language"])

        try:
            user = elevenlabslib.ElevenLabsUser(settings["keyring_elevenlabs_api_key"])
            if not user.get_voice_clone_available():
                msgBox = QtWidgets.QMessageBox()
                msgBox.setText(translate_ui_text("Your ElevenLabs subscription does not support voice cloning. \nSome features won't be available.", settings["ui_language"]))
                msgBox.exec()
        except ValueError:
            errorMessage += "\nElevenLabs API error. API Key may be incorrect."

        if settings["voice_recognition_type"].lower() == "online":
            openai.api_key = settings["keyring_openai_api_key"]
            try:
                openai.Model.list()
            except openai.error.AuthenticationError:
                errorMessage += "\nOpenAI API error. API Key may be incorrect."

        if settings["keyring_deepl_api_key"] != "":
            deeplTranslator = deepl.Translator(settings["keyring_deepl_api_key"]).set_app_info("polyecho", "1.0.0")
            try:
                deeplTranslator.get_usage()
            except deepl.AuthorizationException:
                errorMessage += "\nDeepL API error. API Key may be incorrect."

        if settings["keyring_audo_api_key"] != "":
            audoClient = NoiseRemovalClient(settings["keyring_audo_api_key"])
            try:
                socket = audoClient.connect_websocket("TestID")
                socket.close()
            except websocket.WebSocketBadStatusException:
                errorMessage += "\nAudo API error. API Key may be incorrect."

        if settings["transcription_storage"].lower() == "enable":
            if settings["transcript_save_location"] is None or not os.path.isdir(settings["transcript_save_location"]):
                errorMessage += "\nSpecified transcript save location is not a valid directory."

        try:
            int(settings["loudness_threshold"])
        except ValueError:
            errorMessage += "\nLoudness threshold must be an integer!"

        try:
            float(settings["pause_time_(in_seconds)"])
        except ValueError:
            errorMessage += "\nPause time must be a number!"

        if errorMessage != "":
            msgBox = QtWidgets.QMessageBox()
            msgBox.setText(translate_ui_text(errorMessage, settings["ui_language"]))
            msgBox.exec()
        else:
            keysToPop = list()
            for key, value in settings.items():
                if "keyring_" in key:
                    keyringKey = key[len("keyring_"):]
                    keyring.set_password("polyecho", keyringKey, value)
                    keysToPop.append(key)
            for key in keysToPop:
                settings.pop(key)
            with open("config.json", "w") as fp2:
                json.dump(settings, fp2, indent=4)
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
        self.localWhisperWidgets.layout.addWidget(self.speechRecWidgets, 3, 0, 1, 3)
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
        self.whisperAPIWidgets.layout.addWidget(self.speechRecWidgets, 1, 0, 1, 3)
        self.adjustSize()


def main():
    app = QtWidgets.QApplication([])

    dialog = ConfigDialog()
    dialog.show()

    app.exec()

if __name__ == "__main__":
    main()
