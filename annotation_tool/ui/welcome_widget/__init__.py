import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from utils import resource_path


class WelcomeWidget(QWidget):
    """
    Welcome screen view backed by a Qt Designer .ui file.
    """

    createProjectRequested = pyqtSignal()
    importProjectRequested = pyqtSignal()
    tutorialRequested = pyqtSignal()
    githubRequested = pyqtSignal()
    recentProjectRequested = pyqtSignal(str)
    recentProjectRemoveRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(os.path.join("ui", "welcome_widget", "welcome_widget.ui"))
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
        self.recent_projects_list.itemSelectionChanged.connect(self.recent_projects_list.clearSelection)

    def set_recent_projects(self, paths: list[str]):
        self.recent_projects_list.clear()
        for path in paths:
            if not path:
                continue
            item = QListWidgetItem()
            row_widget = self._build_recent_row(path)
            item.setSizeHint(row_widget.sizeHint())
            self.recent_projects_list.addItem(item)
            self.recent_projects_list.setItemWidget(item, row_widget)

    def _build_recent_row(self, path: str) -> QWidget:
        filename = os.path.basename(path)
        folder_path = os.path.dirname(path) or "."

        row = QWidget()
        row.setObjectName("welcome_recent_item")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(8)

        name_btn = QPushButton(filename)
        name_btn.setObjectName("welcome_recent_file_btn")
        name_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        name_btn.setFlat(True)
        name_btn.setToolTip(path)
        name_btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        name_btn.clicked.connect(lambda _checked=False, p=path: self.recentProjectRequested.emit(p))

        folder_lbl = QLabel(folder_path)
        folder_lbl.setObjectName("welcome_recent_path_lbl")
        folder_lbl.setToolTip(path)
        folder_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        remove_btn = QToolButton()
        remove_btn.setObjectName("welcome_recent_remove_btn")
        remove_btn.setText("×")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setToolTip("Remove from recent datasets")
        remove_btn.clicked.connect(
            lambda _checked=False, p=path: self.recentProjectRemoveRequested.emit(p)
        )

        layout.addWidget(name_btn)
        layout.addWidget(folder_lbl, 1)
        layout.addWidget(remove_btn)
        return row
