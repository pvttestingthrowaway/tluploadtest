import fnmatch
import os
import shutil
import subprocess
import platform
import sys
from zipfile import ZipFile

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from utils import helper
from utils.helper import settings
from utils.customWidgets import *

#Helper functions for ffmpeg download/extract

def download_ffmpeg():
    downloadDir = os.path.join(os.getcwd(), "ffmpeg-dl")
    extractDir = os.path.join(os.getcwd(), 'ffmpeg-bin')
    currentOS = platform.system()
    os.makedirs(downloadDir, exist_ok=True)

    if currentOS == 'Windows':
        urls = ['https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip']
    elif currentOS == 'Darwin':
        urls = ['https://evermeet.cx/ffmpeg/get/zip', 'https://evermeet.cx/ffmpeg/get/ffprobe/zip', 'https://evermeet.cx/ffmpeg/get/ffplay/zip']
    else:
        raise Exception("Unsupported OS")

    for url in urls:
        if currentOS == 'Windows':
            fileName = url.split('/')[-1]
        else:
            fileName = url.split('/')[-2]
            if fileName == "get":
                fileName = "ffmpeg"
        if not fileName.endswith(".zip"):
            fileName += ".zip"
        downloadPath = os.path.join(downloadDir, fileName)
        DownloadDialog(f"Downloading {fileName}", url, downloadPath).exec()
        #Done with the download.
        extract_ffmpeg(downloadPath, extractDir)


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

    app.setStyleSheet(helper.get_stylesheet())

    if "ui_language" not in settings:
        settings["ui_language"] = "System language - syslang"

    try:
        subprocess.check_output('ffmpeg -version', shell=True)
    except subprocess.CalledProcessError:
        # ffmpeg is not in $PATH.
        currentOS = platform.system()
        if currentOS != "Windows" and currentOS != "Darwin":
            message_box = QMessageBox()
            message_box.setText("FFmpeg is missing, but your OS is not supported for auto-download. Please install it yourself.")
            QTimer.singleShot(1, lambda: (message_box.activateWindow(), message_box.raise_()))
            message_box.exec()
            exit()

        # Ensure the dir exists
        os.makedirs(os.path.join(os.getcwd(), "ffmpeg-bin"), exist_ok=True)

        if not os.path.exists(f"ffmpeg-bin/ffmpeg{'.exe' if currentOS == 'Windows' else ''}"):
            # It's not downloaded either. Download it.
            download_ffmpeg()
            if not os.path.exists("ffmpeg-bin/ffmpeg.exe"):
                raise Exception("Download failed! Please try again.")

        # At this point the binary files for ffmpeg are in ffmpeg-bin in the current directory.
        os.environ["PATH"] += os.pathsep + os.path.join(os.getcwd(), "ffmpeg-bin")

    # ffmpeg is installed and in path.
    # Add CUDNN and cublas too.
    venv_root = os.path.dirname(os.path.dirname(sys.executable))
    torch_path = os.path.join(venv_root, 'Lib', 'site-packages', 'torch')
    new_path = None
    # Search for the directory containing 'cudnn_adv*.dll'
    for root, dirs, files in os.walk(torch_path):
        for file in files:
            if fnmatch.fnmatch(file, 'cudnn_adv*.dll'):
                new_path = root
                break
        else:
            continue  # Only executed if the inner loop did NOT break
        break  # Only executed if the inner loop DID break
    #Add it to PATH.
    if new_path is not None:
        os.environ["PATH"] = new_path + os.pathsep + os.environ["PATH"]

    subprocess.call([sys.executable, 'polyEcho.py'])

if __name__=="__main__":
    main()