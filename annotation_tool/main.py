import os
import sys
import multiprocessing

os.environ["PYTORCH_JIT"] = "0"

from PyQt6.QtWidgets import QApplication
from main_window import VideoAnnotationWindow

if __name__ == '__main__':
    multiprocessing.freeze_support()
    
    app = QApplication(sys.argv)
    window = VideoAnnotationWindow()
    window.show()
    sys.exit(app.exec())
