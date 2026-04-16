import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QTreeView, QDialogButtonBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit, QHBoxLayout,
    QFrame, QListWidget, QComboBox, QPushButton, QLabel, QProgressBar,
    QMessageBox, QWidget, QListWidgetItem, QStyle, QButtonGroup, QScrollArea,
    QFileDialog, QCheckBox, QSizePolicy
)
from PyQt6.QtCore import QDir, Qt, QSize, QSettings, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QIcon
from utils import get_square_remove_btn_style

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


class HfDownloadDialog(QDialog):
    downloadRequested = pyqtSignal(dict)

    _SETTINGS_PREFIX = "hf_transfer/download"
    _KEY_URL = f"{_SETTINGS_PREFIX}/url"
    _KEY_SUCCESS_URLS = f"{_SETTINGS_PREFIX}/successful_urls"
    _KEY_OUTPUT_DIR = f"{_SETTINGS_PREFIX}/output_dir"
    _KEY_DRY_RUN = f"{_SETTINGS_PREFIX}/dry_run"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"
    _AVAILABLE_DATASET_URLS = [
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/mvfouls/annotations_train.json",
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/mvfouls/annotations_valid.json",
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/mvfouls/annotations_test.json",
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snas/blob/224p/annotations-train.json",
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snas/blob/224p/annotations-valid.json",
        "https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snas/blob/224p/annotations-test.json",
    ]

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._submitted = False
        self.setWindowTitle("Download Dataset from Hugging Face")
        self.setModal(True)
        self.setMinimumWidth(760)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self.url_combo = QComboBox(self)
        self.url_combo.setEditable(True)
        self.url_combo.addItems(self._AVAILABLE_DATASET_URLS)
        form.addRow("HF URL*", self.url_combo)

        self.output_dir_edit = QLineEdit(self)
        self.output_dir_edit.setPlaceholderText("test_data/Classification/svfouls")
        browse_output_button = QPushButton("Browse...", self)
        browse_output_button.clicked.connect(self._pick_output_dir)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_dir_edit, 1)
        output_row.addWidget(browse_output_button, 0)
        form.addRow("Output Directory*", output_row)

        self.dry_run_checkbox = QCheckBox("Dry-run (estimate only, no downloads)", self)
        form.addRow("", self.dry_run_checkbox)

        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Optional token override")
        form.addRow("HF Token", self.token_edit)

        self.url_combo.setMinimumHeight(34)
        self.url_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for edit in (self.output_dir_edit, self.token_edit):
            edit.setMinimumHeight(34)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setText("Download")
        buttons.accepted.connect(self._on_submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_settings()

    @classmethod
    def _normalize_urls(cls, raw_urls) -> list[str]:
        if raw_urls is None:
            candidates = []
        elif isinstance(raw_urls, str):
            candidates = [raw_urls]
        elif isinstance(raw_urls, (list, tuple)):
            candidates = list(raw_urls)
        else:
            candidates = []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            url = str(item or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            normalized.append(url)
        return normalized

    @classmethod
    def get_successful_urls_from_settings(cls, settings: QSettings | None) -> list[str]:
        if not settings:
            return []
        return cls._normalize_urls(settings.value(cls._KEY_SUCCESS_URLS, []))

    @classmethod
    def add_successful_url_to_settings(cls, settings: QSettings | None, url: str) -> None:
        if not settings:
            return
        clean_url = str(url or "").strip()
        if not clean_url:
            return
        urls = cls.get_successful_urls_from_settings(settings)
        urls.append(clean_url)
        settings.setValue(cls._KEY_SUCCESS_URLS, cls._normalize_urls(urls))
        settings.sync()

    @classmethod
    def remove_successful_url_from_settings(cls, settings: QSettings | None, url: str) -> None:
        if not settings:
            return
        clean_url = str(url or "").strip()
        if not clean_url:
            return
        urls = [item for item in cls.get_successful_urls_from_settings(settings) if item != clean_url]
        settings.setValue(cls._KEY_SUCCESS_URLS, urls)
        settings.sync()

    def _pick_output_dir(self) -> None:
        start_dir = self.output_dir_edit.text().strip() or os.getcwd()
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Output Directory",
            start_dir,
        )
        if chosen:
            self.output_dir_edit.setText(chosen)

    def _validate_and_accept(self) -> bool:
        url = self.url_combo.currentText().strip()
        output_dir = self.output_dir_edit.text().strip()

        if not url:
            QMessageBox.warning(self, "Missing Required Field", "HF URL is required.")
            return False
        if not output_dir:
            QMessageBox.warning(self, "Missing Required Field", "Output directory is required.")
            return False
        return True

    def _on_submit(self) -> None:
        if not self._validate_and_accept():
            return
        payload = self.get_payload()
        self._save_settings()
        self._submitted = True
        self.downloadRequested.emit(payload)
        if not payload.get("dry_run", False):
            self.accept()

    def get_payload(self) -> dict:
        return {
            "url": self.url_combo.currentText().strip(),
            "output_dir": self.output_dir_edit.text().strip(),
            "dry_run": self.dry_run_checkbox.isChecked(),
            "token": self.token_edit.text().strip() or None,
        }

    def was_submitted(self) -> bool:
        return self._submitted

    def _load_settings(self) -> None:
        if not self._settings:
            return
        for saved_url_option in self.get_successful_urls_from_settings(self._settings):
            if self.url_combo.findText(saved_url_option) < 0:
                self.url_combo.addItem(saved_url_option)

        saved_url = str(self._settings.value(self._KEY_URL, "") or "")
        if saved_url:
            idx = self.url_combo.findText(saved_url)
            if idx >= 0:
                self.url_combo.setCurrentIndex(idx)
            else:
                self.url_combo.setEditText(saved_url)
        self.output_dir_edit.setText(str(self._settings.value(self._KEY_OUTPUT_DIR, "") or ""))
        dry_run_raw = self._settings.value(self._KEY_DRY_RUN, False)
        if isinstance(dry_run_raw, str):
            self.dry_run_checkbox.setChecked(dry_run_raw.strip().lower() in {"1", "true", "yes", "on"})
        else:
            self.dry_run_checkbox.setChecked(bool(dry_run_raw))
        self.token_edit.setText(str(self._settings.value(self._KEY_TOKEN, "") or ""))

    def _save_settings(self) -> None:
        if not self._settings:
            return
        self._settings.setValue(self._KEY_URL, self.url_combo.currentText().strip())
        self._settings.setValue(self._KEY_OUTPUT_DIR, self.output_dir_edit.text().strip())
        self._settings.setValue(self._KEY_DRY_RUN, self.dry_run_checkbox.isChecked())
        self._settings.setValue(self._KEY_TOKEN, self.token_edit.text().strip())
        self._settings.sync()


class HfUploadDialog(QDialog):
    _SETTINGS_PREFIX = "hf_transfer/upload"
    _KEY_REPO_ID = f"{_SETTINGS_PREFIX}/repo_id"
    _KEY_REVISION = f"{_SETTINGS_PREFIX}/revision"
    _KEY_COMMIT_MESSAGE = f"{_SETTINGS_PREFIX}/commit_message"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"

    def __init__(
        self,
        opened_json_path: str,
        *,
        hf_defaults: dict | None = None,
        settings: QSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._hf_defaults = dict(hf_defaults or {})
        self.setWindowTitle("Upload Dataset to Hugging Face")
        self.setModal(True)
        self.setMinimumWidth(760)
        self._opened_json_path = str(opened_json_path or "").strip()

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self.repo_id_edit = QLineEdit(self)
        self.repo_id_edit.setPlaceholderText("OpenSportsLab/OSL-loc-tennis-public")
        form.addRow("Repo ID*", self.repo_id_edit)

        self.opened_json_edit = QLineEdit(self._opened_json_path, self)
        self.opened_json_edit.setReadOnly(True)
        form.addRow("Opened Dataset JSON*", self.opened_json_edit)

        self.upload_as_json_checkbox = QCheckBox("Upload as JSON (unchecked: upload as Parquet + WebDataset)", self)
        self.upload_as_json_checkbox.setChecked(True)
        form.addRow("", self.upload_as_json_checkbox)

        self.revision_edit = QLineEdit("main", self)
        self.revision_edit.setPlaceholderText("main")
        form.addRow("Branch*", self.revision_edit)

        self.commit_message_edit = QLineEdit("Upload dataset inputs from JSON", self)
        form.addRow("Commit Message", self.commit_message_edit)

        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Optional token override")
        form.addRow("HF Token", self.token_edit)

        for edit in (
            self.repo_id_edit,
            self.opened_json_edit,
            self.revision_edit,
            self.commit_message_edit,
            self.token_edit,
        ):
            edit.setMinimumHeight(34)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button:
            ok_button.setText("Upload")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_settings()

    def _validate_and_accept(self) -> None:
        repo_id = self.repo_id_edit.text().strip()

        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required.")
            return
        if not self.revision_edit.text().strip():
            QMessageBox.warning(self, "Missing Required Field", "Branch is required.")
            return
        if not self._opened_json_path:
            QMessageBox.warning(self, "Missing Required Field", "Dataset JSON path is required.")
            return
        if not os.path.isfile(self._opened_json_path):
            QMessageBox.warning(
                self,
                "Invalid JSON Path",
                f"Opened dataset JSON file does not exist:\n{self._opened_json_path}",
            )
            return
        self._save_settings()
        self.accept()

    def get_payload(self) -> dict:
        return {
            "repo_id": self.repo_id_edit.text().strip(),
            "json_path": self._opened_json_path,
            "revision": self.revision_edit.text().strip() or "main",
            "commit_message": self.commit_message_edit.text().strip() or "Upload dataset inputs from JSON",
            "token": self.token_edit.text().strip() or None,
            "upload_as_json": self.upload_as_json_checkbox.isChecked(),
        }

    def _load_settings(self) -> None:
        if self._settings:
            self.repo_id_edit.setText(str(self._settings.value(self._KEY_REPO_ID, "") or ""))
            self.revision_edit.setText(str(self._settings.value(self._KEY_REVISION, "main") or "main"))
            self.commit_message_edit.setText(
                str(
                    self._settings.value(
                        self._KEY_COMMIT_MESSAGE,
                        "Upload dataset inputs from JSON",
                    )
                    or "Upload dataset inputs from JSON"
                )
            )
            self.token_edit.setText(str(self._settings.value(self._KEY_TOKEN, "") or ""))

        default_repo_id = str(self._hf_defaults.get("repo_id") or "").strip()
        default_branch = str(self._hf_defaults.get("branch") or "").strip()
        if default_repo_id:
            self.repo_id_edit.setText(default_repo_id)
        if default_branch:
            self.revision_edit.setText(default_branch)

    def _save_settings(self) -> None:
        if not self._settings:
            return
        self._settings.setValue(self._KEY_REPO_ID, self.repo_id_edit.text().strip())
        self._settings.setValue(self._KEY_REVISION, self.revision_edit.text().strip() or "main")
        self._settings.setValue(self._KEY_COMMIT_MESSAGE, self.commit_message_edit.text().strip())
        self._settings.setValue(self._KEY_TOKEN, self.token_edit.text().strip())
        self._settings.sync()


class BusyStatusDialog(QDialog):
    cancelRequested = pyqtSignal()

    def __init__(
        self,
        title: str,
        message: str,
        parent=None,
        *,
        show_cancel: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._cancel_button = None

        layout = QVBoxLayout(self)

        self._label = QLabel(message, self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        layout.addWidget(self._progress)

        if show_cancel:
            button_row = QHBoxLayout()
            button_row.addStretch(1)
            self._cancel_button = QPushButton("Cancel", self)
            self._cancel_button.clicked.connect(self._on_cancel_clicked)
            button_row.addWidget(self._cancel_button)
            layout.addLayout(button_row)

        self.setMinimumWidth(320)

    def set_message(self, message: str) -> None:
        self._label.setText(message)

    def set_cancel_enabled(self, enabled: bool) -> None:
        if self._cancel_button is not None:
            if enabled:
                self._cancel_button.setText("Cancel")
            self._cancel_button.setEnabled(bool(enabled))

    def _on_cancel_clicked(self) -> None:
        if self._cancel_button is not None:
            self._cancel_button.setEnabled(False)
            self._cancel_button.setText("Cancelling...")
        self.cancelRequested.emit()
