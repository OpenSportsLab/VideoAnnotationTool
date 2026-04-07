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

class ProjectTypeDialog(QDialog):
    """
    Project type chooser.
    Shown after clicking 'New Project' to select the operating mode.
    Updated to include Classification, Localization, and Description.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setWindowTitle("Select Project Type")
        self.resize(600, 250) # Widen slightly to fit 3 buttons
        self.selected_mode: str | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        lbl = QLabel("Please select the type of project you want to create:")
        lbl.setProperty("class", "dialog_instruction_lbl")
        layout.addWidget(lbl)

        # Three large buttons side-by-side
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)

        # 1. Classification Button
        self.btn_cls = QPushButton("Classification")
        self.btn_cls.setMinimumSize(QSize(0, 80))
        self.btn_cls.setProperty("class", "project_type_btn") # CSS class for styling
        
        # 2. Localization Button
        self.btn_loc = QPushButton("Localization")
        self.btn_loc.setMinimumSize(QSize(0, 80))
        self.btn_loc.setProperty("class", "project_type_btn")

        # 3. [NEW] Description Button
        self.btn_desc = QPushButton("Description")
        self.btn_desc.setMinimumSize(QSize(0, 80))
        self.btn_desc.setProperty("class", "project_type_btn")

        # 3. [NEW] Description Button
        self.btn_dense = QPushButton("Dense Description")
        self.btn_dense.setMinimumSize(QSize(0, 80))
        self.btn_dense.setProperty("class", "project_type_btn")

        # Add buttons to layout
        btn_layout.addWidget(self.btn_cls)
        btn_layout.addWidget(self.btn_loc)
        btn_layout.addWidget(self.btn_desc) # [NEW]
        btn_layout.addWidget(self.btn_dense) # [NEW]

        layout.addLayout(btn_layout)

        # Connect signals
        # Lambda is used to pass the mode string to the handler
        self.btn_cls.clicked.connect(lambda: self.finalize_selection("classification"))
        self.btn_loc.clicked.connect(lambda: self.finalize_selection("localization"))
        self.btn_desc.clicked.connect(lambda: self.finalize_selection("description")) 
        self.btn_dense.clicked.connect(lambda: self.finalize_selection("dense_description")) # [NEW]

    def finalize_selection(self, mode: str):
        """Stores the selected mode and closes the dialog."""
        self.selected_mode = mode
        self.accept()

class ClassificationTypeDialog(QDialog):
    """
    [NEW] Dialog to ask the user if the new Classification project 
    is Single-View or Multi-View.
    """
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Classification Project Type")
        self.resize(450, 180)
        self.is_multi_view = False # Default to Single-View

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)

        lbl = QLabel("Is this a Single-View or Multi-View project?")
        lbl.setProperty("class", "dialog_instruction_lbl")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(20)

        self.btn_sv = QPushButton("Single-View\n(Individual Videos)")
        self.btn_sv.setMinimumSize(QSize(0, 70))
        self.btn_sv.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.btn_mv = QPushButton("Multi-View\n(Grouped by Folder)")
        self.btn_mv.setMinimumSize(QSize(0, 70))
        self.btn_mv.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self.btn_sv)
        btn_layout.addWidget(self.btn_mv)
        layout.addLayout(btn_layout)

        # Connect signals
        self.btn_sv.clicked.connect(lambda: self.finalize_selection(False))
        self.btn_mv.clicked.connect(lambda: self.finalize_selection(True))

    def finalize_selection(self, is_multi: bool):
        self.is_multi_view = is_multi
        self.accept()

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