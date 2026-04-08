import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QTreeView, QDialogButtonBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit, QHBoxLayout,
    QCheckBox, QFrame, QListWidget, QComboBox, QPushButton, QLabel,
    QMessageBox, QWidget, QListWidgetItem, QStyle, QButtonGroup, QScrollArea
)
from PyQt6.QtCore import QDir, Qt, QSize
from PyQt6.QtGui import QFileSystemModel, QIcon
from utils import get_square_remove_btn_style

class NewDatasetDialog(QDialog):
    """Minimal new-dataset flow with only multiview grouping."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create New Dataset")
        self.resize(420, 180)
        self.is_multi_view = False

        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        lbl = QLabel("Create a blank dataset. All four editor tabs stay available.")
        lbl.setWordWrap(True)
        lbl.setProperty("class", "dialog_instruction_lbl")
        layout.addWidget(lbl)

        self.multiview_checkbox = QCheckBox("Group added samples by parent folder (multiview)")
        self.multiview_checkbox.setChecked(False)
        layout.addWidget(self.multiview_checkbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        self.is_multi_view = self.multiview_checkbox.isChecked()
        self.accept()


class UnsavedChangesDialog(QDialog):
    """Dialog with fixed button order for close-project decisions."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Unsaved Changes")
        self.setModal(True)
        self._action = "cancel"

        layout = QVBoxLayout(self)
        text = QLabel("Unsaved changes will be lost. How do you want to proceed?", self)
        text.setWordWrap(True)
        layout.addWidget(text)

        button_row = QHBoxLayout()
        layout.addLayout(button_row)

        # Keep this explicit order across platforms.
        btn_save = QPushButton("Save", self)
        btn_save_as = QPushButton("Save As", self)
        btn_discard = QPushButton("Close Without Saving", self)
        btn_cancel = QPushButton("Cancel", self)

        button_row.addWidget(btn_save)
        button_row.addWidget(btn_save_as)
        button_row.addWidget(btn_discard)
        button_row.addWidget(btn_cancel)

        btn_save.clicked.connect(lambda: self._accept("save"))
        btn_save_as.clicked.connect(lambda: self._accept("save_as"))
        btn_discard.clicked.connect(lambda: self._accept("discard"))
        btn_cancel.clicked.connect(self.reject)

        btn_save.setDefault(True)
        btn_save.setAutoDefault(True)

    def _accept(self, action: str):
        self._action = action
        self.accept()

    @classmethod
    def get_action(cls, parent=None) -> str:
        dialog = cls(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog._action
        return "cancel"

class FolderPickerDialog(QDialog):
    """
    Custom folder picker that allows multi-selection of folders.
    Used for selecting scene folders when creating a project.
    """

    def __init__(self, initial_dir: str = "", parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Select Scene Folders (Click to Toggle Multiple)")
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        layout.addWidget(QRadioButton("Tip: Click multiple folders to select them. No need to hold Ctrl."))

        self.model = QFileSystemModel()
        self.model.setRootPath(QDir.rootPath())
        self.model.setFilter(QDir.Filter.AllDirs | QDir.Filter.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)

        # Optimize column view (Hide size/type/date, only show name)
        self.tree.setColumnWidth(0, 400)
        for i in range(1, 4):
            self.tree.hideColumn(i)

        # Set initial directory
        start_path = initial_dir if initial_dir and os.path.exists(initial_dir) else QDir.rootPath()
        self.tree.setRootIndex(self.model.index(start_path))

        layout.addWidget(self.tree)

        # Standard OK/Cancel buttons
        bbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        layout.addWidget(bbox)

    def get_selected_folders(self) -> list[str]:
        """Returns a list of absolute paths for the selected folders."""
        indexes = self.tree.selectionModel().selectedRows()
        paths = [self.model.filePath(idx) for idx in indexes]
        return paths
    
class MediaErrorDialog(QMessageBox):
    """
    [NEW] A standardized error dialog for media playback failures.
    Provides a concise explanation and an FFmpeg command to fix the codec issue.
    Technical logs are hidden in the details section to keep the UI clean.
    """
    def __init__(self, error_string: str, parent=None) -> None:
        super().__init__(parent)
        
        self.setIcon(QMessageBox.Icon.Critical)
        
        # Main short title
        self.setWindowTitle("Video Decoding Error")
        self.setText("<b>Unsupported Video Codec Detected</b>")
        
        # Concise explanation with the FFmpeg terminal command
        info_text = (
            "Your system cannot decode this video's format (e.g., AV1, DivX, or Xvid). "
            "The audio might play, but the video hardware decoder has failed.\n\n"
            "To fix this, please transcode your file to a standard H.264 MP4 format. "
            "Run the following command in your terminal:\n\n"
            "ffmpeg -i input.mp4 -vcodec libx264 -acodec aac output.mp4"
        )
        self.setInformativeText(info_text)
        
        # Hide the long, ugly technical error logs inside a collapsible "Show Details..." button
        if error_string:
            self.setDetailedText(f"System Diagnostic Logs:\n{error_string}")
            
        self.setStandardButtons(QMessageBox.StandardButton.Ok)
