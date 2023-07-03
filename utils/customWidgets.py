import os
import threading
from typing import Optional

import keyring
import requests
from PyQt6 import QtWidgets, QtCore, QtGui
from PyQt6.QtCore import QPoint, QRect, Qt, QObject, pyqtSignal, QSize
from PyQt6.QtGui import QPainter, QPen, QColor
from PyQt6.QtWidgets import QStyle, QStyleOptionSlider, QSlider, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QFileDialog, QLineEdit, QCheckBox, QProgressBar, QSizePolicy, QPushButton

from utils import helper
from utils.helper import settings


class SignalEmitter(QObject):
    #Just a dummy helper class for arbitrary signals.
    signal = pyqtSignal()

class StrSignalEmitter(QObject):
    #Just a dummy helper class for arbitrary signals.
    signal = pyqtSignal(str)

class LocalizedDialog(QtWidgets.QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("First time setup")

    def setWindowTitle(self, a0: str) -> None:
        super().setWindowTitle(helper.translate_ui_text(a0))

class LocalizedCheckbox(QCheckBox):
    def __init__(self, configKey, text=None, cacheSkip=False):
        super(LocalizedCheckbox, self).__init__(helper.translate_ui_text(text, cacheSkip=cacheSkip))
        self.cacheSkip = cacheSkip
        self.configKey = configKey
        if configKey not in settings:
            settings[configKey] = False
        self.setChecked(settings[configKey])

    def setText(self, a0: str) -> None:
        super(LocalizedCheckbox, self).setText(helper.translate_ui_text(a0, cacheSkip=self.cacheSkip))

    def get_value(self):
        return self.isChecked()


class LocalizedLabel(QLabel):
    def __init__(self, text=None, cacheSkip=False):
        super(LocalizedLabel, self).__init__(helper.translate_ui_text(text, cacheSkip=cacheSkip))
        self.cacheSkip = cacheSkip

    def setText(self, a0: str) -> None:
        super(LocalizedLabel, self).setText(helper.translate_ui_text(a0, cacheSkip=self.cacheSkip))

class LocalizedCenteredLabel(LocalizedLabel):
    def __init__(self, text=None, cacheSkip=False, wordWrap=False):
        super(LocalizedCenteredLabel, self).__init__(text, cacheSkip=cacheSkip)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(wordWrap)

class CenteredLabel(QLabel):
    def __init__(self, text=None, wordWrap=False):
        super(CenteredLabel, self).__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(wordWrap)

class InfoButton(QtWidgets.QPushButton):

    def __init__(self, info, parentLabel, isDir=False):
        super().__init__()
        self.info = helper.translate_ui_text(info)
        self.setAccessibleName(helper.translate_ui_text(f"Info for {parentLabel}"))
        self.setAccessibleDescription(helper.translate_ui_text("Opens a messagebox with information."))
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
            self.clicked.connect(self.show_info)

    def show_info(self):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setTextFormat(Qt.TextFormat.RichText)
        msgBox.setText(self.info)
        msgBox.exec()

class LabeledInput(QtWidgets.QWidget):
    """
    This widget has a label and below it an input.
    Arguments:
        label: The text to put above the input
        configKey: The corresponding configKey to pull the default value from and save the user-selected value to
        data: The options to choose from. If it's a string, the input will be a lineEdit, if it's a list, it will be a comboBox.
        info: If it's not None, then an 'info' button will be created which will show the text contained in this argument in a messageBox when clicked.
        infoIsDir: Replaces the info button with a directory button, which opens a file browser.
        protected: Saves the config data to the system keyring instead of the 'settings' dict.
    fixedComboSize and localizeComboBox can be ignored.
    """
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
            self.combo_box.setAccessibleName(helper.translate_ui_text(f"{label} combobox"))
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
            self.line_edit.setAccessibleName(helper.translate_ui_text(f"{label} text input"))
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
                self.line_edit.setText(str(currentValue))

        self.layout.addWidget(self.input_widget)

        if info is not None:
            self.info_button = InfoButton(info, label, infoIsDir)
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
            button_texts[index] = helper.translate_ui_text(text)

        self.layout = QtWidgets.QGridLayout(self)
        self.selected_button = 0  # add an instance variable to track selected button

        self.label = LocalizedCenteredLabel(label)
        self.layout.addWidget(self.label, 0, 0, 1, 2)  # add to the top

        self.button_widget = QtWidgets.QWidget()
        self.button_layout = QtWidgets.QHBoxLayout(self.button_widget)
        self.button_layout.setSpacing(0)  # adjust the space between buttons

        self.button1 = QtWidgets.QPushButton(button_texts[0])
        self.button1.clicked.connect(lambda: self.button_clicked(0, callbacks[0]))
        self.button1.setAccessibleName(helper.translate_ui_text(f"{button_texts[0]} ({label} left button)"))
        self.button1.setAccessibleDescription(helper.translate_ui_text(f"Left button of the {label} ToggleButton. Sets the UI state to {button_texts[0]} if it isn't already."))

        self.button2 = QtWidgets.QPushButton(button_texts[1])
        self.button2.clicked.connect(lambda: self.button_clicked(1, callbacks[1]))
        self.button2.setAccessibleName(helper.translate_ui_text(f"{button_texts[1]} ({label} right button)"))
        self.button2.setAccessibleDescription(helper.translate_ui_text(f"Right button of the {label} ToggleButton. Sets the UI state to {button_texts[1]} if it isn't already."))

        self.button_layout.addWidget(self.button1)
        self.button_layout.addWidget(self.button2)
        self.lower_layout = QHBoxLayout()
        self.lower_layout.addWidget(self.button_widget)
        self.lower_layout.setSpacing(0)
        self.setAccessibleName(helper.translate_ui_text(f"{label} toggle button"))
        self.setAccessibleDescription(helper.translate_ui_text("Contains two buttons which allow you to modify the state of the UI."))
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
            self.info_button = InfoButton(info, label)
            self.lower_layout.addWidget(self.info_button)

    def show_info(self, info):
        msgBox = QtWidgets.QMessageBox()
        msgBox.setText(info)
        msgBox.exec()

    def button_clicked(self, button_index, callback):
        self.selected_button = button_index  # update the selected button index
        self.button1.setStyleSheet('' if button_index else f'background-color: {helper.colors_dict["toggle_color"]}')
        self.button2.setStyleSheet(f'background-color: {helper.colors_dict["toggle_color"]}' if button_index else '')
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
        if configKey in settings:
            self.sl.setSliderPosition(settings[configKey])
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
        self.layout.addWidget(LocalizedLabel("VRAM usage, RAM usage:"))

    def paintEvent(self, e):

        super(LabeledSlider,self).paintEvent(e)
        style=self.sl.style()
        painter=QPainter(self)
        pen = QPen()
        pen.setColor(QColor(helper.colors_dict["text_color"]))
        painter.setPen(pen)
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
                bottom=self.rect().bottom()-3

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

                bottom=y_loc+length//2+rect.height()//2+self.top_margin-5
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
#Note: Entirely unused due to azure support being scrapped.
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

class AudioButton(QPushButton):
    def __init__(self, bgColor, icon=None, assignedLabels:Optional[list]=None, *args, **kwargs):
        super(AudioButton, self).__init__(*args, **kwargs)
        self.bgColor = None
        self.previousColor = None
        self.assignedLabels = assignedLabels
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
        if self.assignedLabels is not None:
            for label in self.assignedLabels:
                label.setMaximumWidth(self.width())

class DownloadDialog(QtWidgets.QDialog):
    def __init__(self, text, url, location):
        super().__init__()
        self.setWindowTitle(helper.translate_ui_text('Download Progress'))
        self.url = url
        self.location = location
        self.signalEmitter = SignalEmitter()
        self.signalEmitter.signal.connect(lambda: self.done(0))
        self.layout = QtWidgets.QVBoxLayout()
        self.label = LocalizedCenteredLabel(text)
        self.layout.addWidget(self.label)

        self.progress = QProgressBar(self)
        self.layout.addWidget(self.progress)

        self.setLayout(self.layout)

        self.download_thread = threading.Thread(target=self.download_file)

    def download_file(self):
        response = requests.get(self.url, stream=True)
        total_size_in_bytes = response.headers.get('content-length')

        if total_size_in_bytes is None:  # If 'content-length' is not found in headers
            self.progress.setRange(0, 0)  # Set progress bar to indeterminate state
        else:
            total_size_in_bytes = int(total_size_in_bytes)
            self.progress.setMaximum(100)

        block_size = 1024  # 1 Kibibyte
        progress_tracker = 0

        try:
            response.raise_for_status()
            with open(self.location, 'wb') as file:
                for data in response.iter_content(block_size):
                    progress_tracker += len(data)
                    file.write(data)
                    if total_size_in_bytes is not None:  # Only update if 'content-length' was found
                        self.update_progress_bar(progress_tracker, total_size_in_bytes)
        except requests.exceptions.RequestException as e:
            if os.path.exists(self.location):
                os.remove(self.location)
            raise
        self.signalEmitter.signal.emit()

    def finish(self):
        self.done(0)
    def update_progress_bar(self, progress_tracker, total_size_in_bytes):
        percent_completed = (progress_tracker / total_size_in_bytes) * 100
        self.progress.setValue(int(percent_completed))

    def exec(self):
        self.download_thread.start()
        super().exec()

    def show(self):
        self.download_thread.start()
        super().show()