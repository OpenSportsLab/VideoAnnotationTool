import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget

from utils import resource_path


class WelcomeWidget(QWidget):
    """
    Welcome screen view backed by a Qt Designer .ui file.
    """

    createProjectRequested = pyqtSignal()
    importProjectRequested = pyqtSignal()
    tutorialRequested = pyqtSignal()
    githubRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(os.path.join("ui", "common", "welcome_widget", "welcome_widget.ui"))
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load WelcomeWidget UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.setObjectName("welcome_page")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._load_logo()
        self._setup_connections()

    def _load_logo(self):
        logo_path = resource_path(os.path.join("image", "logo.png"))
        pixmap = QPixmap(logo_path)

        if not pixmap.isNull():
            scaled_pixmap = pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.logo_lbl.setPixmap(scaled_pixmap)
        else:
            self.logo_lbl.setText("(Logo missing)")

    def _setup_connections(self):
        self.create_btn.clicked.connect(self.createProjectRequested.emit)
        self.import_btn.clicked.connect(self.importProjectRequested.emit)
        self.tutorial_btn.clicked.connect(self.tutorialRequested.emit)
        self.github_btn.clicked.connect(self.githubRequested.emit)
