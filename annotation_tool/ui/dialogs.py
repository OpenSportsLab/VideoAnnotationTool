import html
import os
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QTreeView, QDialogButtonBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit, QHBoxLayout,
    QFrame, QListWidget, QComboBox, QPushButton, QLabel, QProgressBar,
    QMessageBox, QWidget, QListWidgetItem, QStyle, QButtonGroup, QScrollArea,
    QFileDialog, QCheckBox, QSizePolicy, QSpinBox
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
    Standardized dialog for media playback failures.
    """

    def __init__(
        self,
        error_string: str,
        parent=None,
        *,
        title: str = "Video Decoding Error",
        text: str = "<b>Unsupported Video Codec Detected</b>",
        informative_text: str = "",
    ) -> None:
        super().__init__(parent)

        self.setIcon(QMessageBox.Icon.Critical)
        self.setWindowTitle(title)
        self.setText(text)
        if informative_text:
            self.setInformativeText(informative_text)

        if error_string:
            self.setDetailedText(f"System Diagnostic Logs:\n{error_string}")

        self.setStandardButtons(QMessageBox.StandardButton.Ok)


class HfDownloadDialog(QDialog):
    downloadRequested = pyqtSignal(dict)

    _SETTINGS_PREFIX = "hf_transfer/download"
    _KEY_URL = f"{_SETTINGS_PREFIX}/url"
    _KEY_REPO_ID = f"{_SETTINGS_PREFIX}/repo_id"
    _KEY_REVISION = f"{_SETTINGS_PREFIX}/revision"
    _KEY_SPLIT = f"{_SETTINGS_PREFIX}/split"
    _KEY_DOWNLOAD_FORMAT = f"{_SETTINGS_PREFIX}/download_format"
    _KEY_SUCCESS_TRANSFERS = f"{_SETTINGS_PREFIX}/successful_transfers"
    _KEY_SUCCESS_URLS = f"{_SETTINGS_PREFIX}/successful_urls"
    _KEY_OUTPUT_DIR = f"{_SETTINGS_PREFIX}/output_dir"
    _KEY_DRY_RUN = f"{_SETTINGS_PREFIX}/dry_run"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"
    _DEFAULT_REPOS = [
        "OpenSportsLab/OSL-XFoul",
        "OpenSportsLab/OSL-SoccerNet",
        "OpenSportsLab/OSL-SNBAS",
    ]

    _AVAILABLE_DATASET_TRANSFERS = [
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "test", "download_format": "parquet"},
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "valid", "download_format": "parquet"},
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "train", "download_format": "parquet"},
        {"repo_id": "OpenSportsLab/soccernetpro-classification-vars", "revision": "mvfouls", "split": "annotations_test", "download_format": "json"},
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

        # Repo ID combo box with default repos and download history
        self.repo_id_combo = QComboBox(self)
        self.repo_id_combo.setEditable(True)
        self.repo_id_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.repo_id_combo.setMinimumHeight(34)
        self.repo_id_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Repo ID*", self.repo_id_combo)

        # Revision combo box with fetch capability
        revision_layout = QHBoxLayout()
        self.revision_combo = QComboBox(self)
        self.revision_combo.setEditable(True)
        self.revision_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.revision_combo.addItem("main")
        self.revision_combo.setMinimumHeight(34)
        self.revision_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        revision_layout.addWidget(self.revision_combo, 1)

        self.fetch_revisions_btn = QPushButton("Fetch Revisions", self)
        self.fetch_revisions_btn.setMinimumHeight(34)
        self.fetch_revisions_btn.setMaximumWidth(160)
        self.fetch_revisions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_revisions_btn.clicked.connect(self._on_fetch_revisions)
        revision_layout.addWidget(self.fetch_revisions_btn, 0)
        form.addRow("Branch*", revision_layout)

        self.split_combo = QComboBox(self)
        self.split_combo.setEditable(True)
        self.split_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.split_combo.addItems(["train", "valid", "test", "challenge"])
        self.split_combo.setCurrentText("test")
        self.split_combo.setMinimumHeight(34)
        self.split_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Split*", self.split_combo)

        self.download_format_combo = QComboBox(self)
        self.download_format_combo.addItem("Parquet + WebDataset", "parquet")
        self.download_format_combo.addItem("JSON + referenced inputs", "json")
        form.addRow("Format*", self.download_format_combo)

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

        self.download_format_combo.setMinimumHeight(34)
        self.download_format_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for edit in (self.split_combo, self.output_dir_edit, self.token_edit):
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

        # Hugging Face repo link label
        self.hf_repo_link_label = QLabel(self)
        self.hf_repo_link_label.setOpenExternalLinks(True)
        self.hf_repo_link_label.setTextFormat(Qt.TextFormat.RichText)
        self.hf_repo_link_label.setWordWrap(True)
        self.hf_repo_link_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.hf_repo_link_label.setStyleSheet(
            "color: #3498db; font-size: 12px; padding: 4px;"
        )
        layout.addWidget(self.hf_repo_link_label)

        self._load_settings()
        self._update_hf_link()

        # Update link dynamically as user types
        self.repo_id_combo.editTextChanged.connect(self._update_hf_link)
        self.revision_combo.editTextChanged.connect(self._update_hf_link)

    @classmethod
    @classmethod
    def _normalize_transfer(cls, transfer: dict | None) -> dict:
        payload = transfer if isinstance(transfer, dict) else {}
        return {
            "repo_id": str(payload.get("repo_id") or "").strip(),
            "revision": str(payload.get("revision") or "main").strip() or "main",
            "split": str(payload.get("split") or "").strip(),
            "download_format": str(payload.get("download_format") or "parquet").strip().lower() or "parquet",
        }

    @classmethod
    def _transfer_key(cls, transfer: dict | None) -> str:
        normalized = cls._normalize_transfer(transfer)
        if not normalized["repo_id"] or not normalized["split"]:
            return ""
        return "|".join(
            [
                normalized["repo_id"],
                normalized["revision"],
                normalized["split"],
                normalized["download_format"],
            ]
        )

    @classmethod
    def _transfer_from_key(cls, key: str) -> dict:
        parts = str(key or "").split("|")
        if len(parts) != 4:
            return {}
        return cls._normalize_transfer(
            {
                "repo_id": parts[0],
                "revision": parts[1],
                "split": parts[2],
                "download_format": parts[3],
            }
        )

    @classmethod
    def _normalize_transfers(cls, raw_transfers) -> list[str]:
        if raw_transfers is None:
            candidates = []
        elif isinstance(raw_transfers, str):
            candidates = [raw_transfers]
        elif isinstance(raw_transfers, (list, tuple)):
            candidates = list(raw_transfers)
        else:
            candidates = []

        normalized: list[str] = []
        seen: set[str] = set()
        for item in candidates:
            key = str(item or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            normalized.append(key)
        return normalized

    @classmethod
    def get_successful_transfers_from_settings(cls, settings: QSettings | None) -> list[str]:
        if not settings:
            return []
        return cls._normalize_transfers(settings.value(cls._KEY_SUCCESS_TRANSFERS, []))

    @classmethod
    def add_successful_transfer_to_settings(cls, settings: QSettings | None, transfer: dict) -> None:
        if not settings:
            return
        key = cls._transfer_key(transfer)
        if not key:
            return
        transfers = cls.get_successful_transfers_from_settings(settings)
        transfers.append(key)
        settings.setValue(cls._KEY_SUCCESS_TRANSFERS, cls._normalize_transfers(transfers))
        settings.sync()

    @classmethod
    def remove_successful_transfer_from_settings(cls, settings: QSettings | None, transfer: dict) -> None:
        if not settings:
            return
        key = cls._transfer_key(transfer)
        if not key:
            return
        transfers = [item for item in cls.get_successful_transfers_from_settings(settings) if item != key]
        settings.setValue(cls._KEY_SUCCESS_TRANSFERS, transfers)
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
        repo_id = self.repo_id_combo.currentText().strip()
        revision = self.revision_combo.currentText().strip()
        split = self.split_combo.currentText().strip()
        output_dir = self.output_dir_edit.text().strip()

        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required.")
            return False
        if not revision:
            QMessageBox.warning(self, "Missing Required Field", "Branch is required.")
            return False
        if not split:
            QMessageBox.warning(self, "Missing Required Field", "Split is required.")
            return False
        if not output_dir:
            QMessageBox.warning(self, "Missing Required Field", "Output directory is required.")
            return False
        if self.dry_run_checkbox.isChecked() and self.download_format_combo.currentData() == "parquet":
            QMessageBox.warning(self, "Unsupported Dry-Run", "Dry-run is available only for JSON downloads.")
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
            "repo_id": self.repo_id_combo.currentText().strip(),
            "revision": self.revision_combo.currentText().strip() or "main",
            "split": self.split_combo.currentText().strip(),
            "download_format": str(self.download_format_combo.currentData() or "parquet"),
            "output_dir": self.output_dir_edit.text().strip(),
            "dry_run": self.dry_run_checkbox.isChecked(),
            "token": self.token_edit.text().strip() or None,
        }

    def was_submitted(self) -> bool:
        return self._submitted

    def _load_settings(self) -> None:
        if not self._settings:
            return
        saved_transfer = {
            "repo_id": str(self._settings.value(self._KEY_REPO_ID, "") or ""),
            "revision": str(self._settings.value(self._KEY_REVISION, "main") or "main"),
            "split": str(self._settings.value(self._KEY_SPLIT, "") or ""),
            "download_format": str(self._settings.value(self._KEY_DOWNLOAD_FORMAT, "parquet") or "parquet"),
        }
        if not saved_transfer["repo_id"] or not saved_transfer["split"]:
            saved_transfer = self._AVAILABLE_DATASET_TRANSFERS[0]
        self._apply_transfer(saved_transfer)
        # Populate repo ID combo with defaults + history
        self._populate_repo_id_combo()
        # Ensure the current revision is set in the combo box
        current_rev = self.revision_combo.currentText()
        if not current_rev:
            self.revision_combo.setCurrentText("main")
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
        payload = self.get_payload()
        self._settings.setValue(self._KEY_REPO_ID, payload["repo_id"])
        self._settings.setValue(self._KEY_REVISION, payload["revision"])
        self._settings.setValue(self._KEY_SPLIT, payload["split"])
        self._settings.setValue(self._KEY_DOWNLOAD_FORMAT, payload["download_format"])
        self._settings.setValue(self._KEY_OUTPUT_DIR, self.output_dir_edit.text().strip())
        self._settings.setValue(self._KEY_DRY_RUN, self.dry_run_checkbox.isChecked())
        self._settings.setValue(self._KEY_TOKEN, self.token_edit.text().strip())
        self._settings.sync()

    def _apply_transfer(self, transfer: dict) -> None:
        normalized = self._normalize_transfer(transfer)
        self.repo_id_combo.setCurrentText(normalized["repo_id"])
        self.revision_combo.setCurrentText(normalized["revision"])
        self.split_combo.setCurrentText(normalized["split"])
        index = self.download_format_combo.findData(normalized["download_format"])
        self.download_format_combo.setCurrentIndex(index if index >= 0 else 0)

    def _populate_repo_id_combo(self) -> None:
        """Populate the repo_id_combo with default repos merged with successful download history."""
        if not self._settings:
            return

        # Get default repositories
        default_repos = list(self._DEFAULT_REPOS)

        # Get successful transfer repo IDs from settings (deduplicated, reversed for recent-first order)
        successful_transfers = self.get_successful_transfers_from_settings(self._settings)
        history_repos: list[str] = []
        for key in successful_transfers:
            parts = key.split("|")
            if len(parts) >= 1 and parts[0]:
                repo = parts[0].strip()
                if repo and repo not in history_repos and repo not in default_repos:
                    history_repos.append(repo)

        # Reverse to show most recent first
        history_repos = list(reversed(history_repos))

        # Merge: default repos first, then history repos right after (no separator)
        merged_repos = list(default_repos) + history_repos

        # Clear and repopulate
        current = self.repo_id_combo.currentText()
        self.repo_id_combo.clear()
        self.repo_id_combo.addItems(merged_repos)

        # Restore previous selection if valid
        if current and self.repo_id_combo.findText(current) >= 0:
            self.repo_id_combo.setCurrentText(current)

    def _on_fetch_revisions(self) -> None:
        """Fetch available branches/revisions from Hugging Face for the current repo_id."""
        repo_id = self.repo_id_combo.currentText().strip()
        if not repo_id:
            QMessageBox.warning(self, "Missing Repo ID", "Please enter a Repo ID first.")
            return

        self.fetch_revisions_btn.setEnabled(False)
        self.fetch_revisions_btn.setText("Fetching...")
        self.revision_combo.clear()

        from PyQt6.QtCore import QThread

        class _FetchRevisionsWorker(QThread):
            revisionsReady = pyqtSignal(list)
            fetchError = pyqtSignal(str)

            def __init__(self, repo_id: str, token: str | None) -> None:
                super().__init__()
                self._repo_id = repo_id
                self._token = token

            def run(self) -> None:
                try:
                    from huggingface_hub import HfApi
                    api = HfApi()
                    refs = api.list_repo_refs(self._repo_id, repo_type="dataset")
                    branch_names = [b.name for b in refs.branches] if hasattr(refs, "branches") and refs.branches else []
                    self.revisionsReady.emit(branch_names)
                except Exception as exc:
                    self.fetchError.emit(str(exc))

        self._fetch_worker = _FetchRevisionsWorker(repo_id, self.token_edit.text().strip() or None)
        self._fetch_worker.revisionsReady.connect(self._on_revisions_fetched)
        self._fetch_worker.fetchError.connect(self._on_revisions_fetch_error)
        self._fetch_worker.finished.connect(lambda: self._cleanup_fetch_worker())
        self._fetch_worker.start()

    def _on_revisions_fetched(self, branches: list) -> None:
        if not branches:
            QMessageBox.information(self, "No Revisions Found", "No branches found on this repository.")
        else:
            current = self.revision_combo.currentText()
            self.revision_combo.clear()
            # Sort branches: 'main' first, then alphabetically
            sorted_branches = sorted(branches, key=lambda x: (x != "main", x))
            self.revision_combo.addItems(sorted_branches)
            # Restore previous selection if it's still valid
            if current and current in branches:
                self.revision_combo.setCurrentText(current)
        self.fetch_revisions_btn.setEnabled(True)
        self.fetch_revisions_btn.setText("Fetch Revisions")

    def _on_revisions_fetch_error(self, error_msg: str) -> None:
        QMessageBox.warning(
            self,
            "Failed to Fetch Revisions",
            f"Could not fetch branches from Hugging Face.\n\nError:\n{error_msg}",
        )
        self.fetch_revisions_btn.setEnabled(True)
        self.fetch_revisions_btn.setText("Fetch Revisions")

    def _cleanup_fetch_worker(self) -> None:
        self._fetch_worker = None

    def _update_hf_link(self) -> None:
        """Update the Hugging Face repo link based on current repo_id and revision."""
        repo_id = self.repo_id_combo.currentText().strip()
        revision = self.revision_combo.currentText().strip() or "main"

        if repo_id:
            url = f"https://huggingface.co/datasets/{repo_id}/tree/{revision}"
            safe_repo_id = html.escape(repo_id)
            safe_revision = html.escape(revision)
            link_text = (
                f'View dataset on Hugging Face: '
                f'<a href="{url}"><b>{safe_repo_id}</b>@<b>{safe_revision}</b></a>'
            )
            self.hf_repo_link_label.setText(link_text)
            self.hf_repo_link_label.setToolTip(f"Click to open {url}")
        else:
            self.hf_repo_link_label.setText("Enter a Repo ID to view the dataset on Hugging Face")
            self.hf_repo_link_label.setToolTip("")


class HfUploadDialog(QDialog):
    _SETTINGS_PREFIX = "hf_transfer/upload"
    _DEFAULT_SHARD_SIZE_BYTES = 1_000_000_000
    _SHARD_SIZE_UNIT_BYTES = 1_000_000
    _KEY_REPO_ID = f"{_SETTINGS_PREFIX}/repo_id"
    _KEY_REVISION = f"{_SETTINGS_PREFIX}/revision"
    _KEY_SPLIT = f"{_SETTINGS_PREFIX}/split"
    _KEY_COMMIT_MESSAGE = f"{_SETTINGS_PREFIX}/commit_message"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"
    _KEY_UPLOAD_AS_JSON = f"{_SETTINGS_PREFIX}/upload_as_json"
    _KEY_SHARD_SIZE = f"{_SETTINGS_PREFIX}/shard_size"
    _KEY_SAMPLES_PER_SHARD = f"{_SETTINGS_PREFIX}/samples_per_shard"

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

        # Repo ID combo (editable) with defaults + history (populated later)
        self.repo_id_combo = QComboBox(self)
        self.repo_id_combo.setEditable(True)
        self.repo_id_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        # Start with download defaults for consistency
        self.repo_id_combo.addItems(list(HfDownloadDialog._DEFAULT_REPOS))
        self.repo_id_combo.setMinimumHeight(34)
        self.repo_id_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Repo ID*", self.repo_id_combo)

        # Revision combo (editable) with fetch capability to mirror download dialog
        revision_layout = QHBoxLayout()
        self.revision_combo = QComboBox(self)
        self.revision_combo.setEditable(True)
        self.revision_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.revision_combo.addItem("main")
        self.revision_combo.setMinimumHeight(34)
        self.revision_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        revision_layout.addWidget(self.revision_combo, 1)

        self.fetch_revisions_btn = QPushButton("Fetch Revisions", self)
        self.fetch_revisions_btn.setMinimumHeight(34)
        self.fetch_revisions_btn.setMaximumWidth(160)
        self.fetch_revisions_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fetch_revisions_btn.clicked.connect(self._on_fetch_revisions)
        revision_layout.addWidget(self.fetch_revisions_btn, 0)
        form.addRow("Branch*", revision_layout)

        # Split combo matches download dialog
        self.split_combo = QComboBox(self)
        self.split_combo.setEditable(True)
        self.split_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.split_combo.addItems(["train", "valid", "test", "challenge"])
        self.split_combo.setCurrentText("test")
        self.split_combo.setMinimumHeight(34)
        self.split_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        form.addRow("Split*", self.split_combo)

        self.opened_json_edit = QLineEdit(self._opened_json_path, self)
        self.opened_json_edit.setReadOnly(True)
        form.addRow("Opened Dataset JSON*", self.opened_json_edit)

        self.upload_as_json_checkbox = QCheckBox("Upload as JSON (unchecked: upload as Parquet + WebDataset)", self)
        self.upload_as_json_checkbox.setChecked(True)
        form.addRow("", self.upload_as_json_checkbox)

        self.shard_size_spin = QSpinBox(self)
        self.shard_size_spin.setRange(1, 1_000_000)
        self.shard_size_spin.setValue(self._DEFAULT_SHARD_SIZE_BYTES // self._SHARD_SIZE_UNIT_BYTES)
        self.shard_size_spin.setSuffix(" MB")
        self.shard_size_spin.setToolTip("Target TAR shard size for Parquet + WebDataset upload mode.")
        form.addRow("Shard Size", self.shard_size_spin)

        self.commit_message_edit = QLineEdit("Upload dataset inputs from JSON", self)
        form.addRow("Commit Message", self.commit_message_edit)

        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Optional token override")
        form.addRow("HF Token", self.token_edit)

        for edit in (
            self.repo_id_combo,
            self.split_combo,
            self.opened_json_edit,
            self.revision_combo,
            self.commit_message_edit,
            self.token_edit,
        ):
            edit.setMinimumHeight(34)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.shard_size_spin.setMinimumHeight(34)
        self.shard_size_spin.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

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

        self.upload_as_json_checkbox.toggled.connect(self._update_parquet_controls_state)
        self._load_settings()
        self._update_parquet_controls_state(self.upload_as_json_checkbox.isChecked())

    def _validate_and_accept(self) -> None:
        repo_id = self.repo_id_combo.currentText().strip()

        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required.")
            return
        if not self.split_combo.currentText().strip():
            QMessageBox.warning(self, "Missing Required Field", "Split is required.")
            return
        if not self.revision_combo.currentText().strip():
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
            "repo_id": self.repo_id_combo.currentText().strip(),
            "json_path": self._opened_json_path,
            "revision": self.revision_combo.currentText().strip() or "main",
            "split": self.split_combo.currentText().strip(),
            "commit_message": self.commit_message_edit.text().strip() or "Upload dataset inputs from JSON",
            "token": self.token_edit.text().strip() or None,
            "upload_as_json": self.upload_as_json_checkbox.isChecked(),
            "shard_mode": "size",
            "shard_size": int(self.shard_size_spin.value()) * self._SHARD_SIZE_UNIT_BYTES,
        }

    def _load_settings(self) -> None:
        if self._settings:
            self.repo_id_combo.setCurrentText(str(self._settings.value(self._KEY_REPO_ID, "") or ""))
            self.revision_combo.setCurrentText(str(self._settings.value(self._KEY_REVISION, "main") or "main"))
            self.split_combo.setCurrentText(str(self._settings.value(self._KEY_SPLIT, "") or ""))
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
            upload_as_json_raw = self._settings.value(self._KEY_UPLOAD_AS_JSON, True)
            if isinstance(upload_as_json_raw, str):
                self.upload_as_json_checkbox.setChecked(
                    upload_as_json_raw.strip().lower() in {"1", "true", "yes", "on"}
                )
            else:
                self.upload_as_json_checkbox.setChecked(bool(upload_as_json_raw))
            has_saved_shard_size = self._settings.contains(self._KEY_SHARD_SIZE)
            saved_shard_size = self._settings.value(self._KEY_SHARD_SIZE, self._DEFAULT_SHARD_SIZE_BYTES)
            try:
                parsed_shard_size = int(saved_shard_size)
            except (TypeError, ValueError):
                parsed_shard_size = self._DEFAULT_SHARD_SIZE_BYTES
            if not has_saved_shard_size and self._settings.contains(self._KEY_SAMPLES_PER_SHARD):
                legacy_value = self._settings.value(self._KEY_SAMPLES_PER_SHARD, self._DEFAULT_SHARD_SIZE_BYTES)
                try:
                    parsed_legacy_value = int(legacy_value)
                except (TypeError, ValueError):
                    parsed_legacy_value = self._DEFAULT_SHARD_SIZE_BYTES
                parsed_shard_size = (
                    parsed_legacy_value
                    if parsed_legacy_value >= self._SHARD_SIZE_UNIT_BYTES
                    else self._DEFAULT_SHARD_SIZE_BYTES
                )
            shard_size_mb = max(1, (parsed_shard_size + self._SHARD_SIZE_UNIT_BYTES - 1) // self._SHARD_SIZE_UNIT_BYTES)
            self.shard_size_spin.setValue(int(shard_size_mb))

        default_repo_id = str(self._hf_defaults.get("repo_id") or "").strip()
        default_branch = str(self._hf_defaults.get("branch") or "").strip()
        default_split = str(self._hf_defaults.get("split") or "").strip()
        inferred_split = os.path.splitext(os.path.basename(self._opened_json_path))[0]
        # Populate repo combo with defaults + history, then apply hf defaults if provided
        self._populate_repo_id_combo()
        if default_repo_id:
            self.repo_id_combo.setCurrentText(default_repo_id)
        if default_branch:
            self.revision_combo.setCurrentText(default_branch)
        if default_split:
            self.split_combo.setCurrentText(default_split)
        elif not self.split_combo.currentText().strip() and inferred_split:
            self.split_combo.setCurrentText(inferred_split)

    def _save_settings(self) -> None:
        if not self._settings:
            return
        self._settings.setValue(self._KEY_REPO_ID, self.repo_id_combo.currentText().strip())
        self._settings.setValue(self._KEY_REVISION, self.revision_combo.currentText().strip() or "main")
        self._settings.setValue(self._KEY_SPLIT, self.split_combo.currentText().strip())
        self._settings.setValue(self._KEY_COMMIT_MESSAGE, self.commit_message_edit.text().strip())
        self._settings.setValue(self._KEY_TOKEN, self.token_edit.text().strip())
        self._settings.setValue(self._KEY_UPLOAD_AS_JSON, self.upload_as_json_checkbox.isChecked())
        self._settings.setValue(
            self._KEY_SHARD_SIZE,
            int(self.shard_size_spin.value()) * self._SHARD_SIZE_UNIT_BYTES,
        )
        self._settings.sync()

    def _update_parquet_controls_state(self, upload_as_json: bool) -> None:
        # Parquet-only option: disable it when JSON upload mode is selected.
        self.shard_size_spin.setEnabled(not bool(upload_as_json))

    def _populate_repo_id_combo(self) -> None:
        """Populate the repo_id combo with default repos merged with successful download history."""
        if not self._settings:
            return

        # Get default repositories from download dialog for consistency
        default_repos = list(HfDownloadDialog._DEFAULT_REPOS)

        successful_transfers = HfDownloadDialog.get_successful_transfers_from_settings(self._settings)
        history_repos: list[str] = []
        for key in successful_transfers:
            parts = key.split("|")
            if len(parts) >= 1 and parts[0]:
                repo = parts[0].strip()
                if repo and repo not in history_repos and repo not in default_repos:
                    history_repos.append(repo)

        # Reverse to show most recent first
        history_repos = list(reversed(history_repos))

        # Merge: default repos first, then history repos right after (no separator)
        merged_repos = list(default_repos) + history_repos

        # Clear and repopulate
        current = self.repo_id_combo.currentText()
        self.repo_id_combo.clear()
        self.repo_id_combo.addItems(merged_repos)

        # Restore previous selection if valid
        if current and self.repo_id_combo.findText(current) >= 0:
            self.repo_id_combo.setCurrentText(current)

    def _on_fetch_revisions(self) -> None:
        """Fetch available branches/revisions from Hugging Face for the current repo_id."""
        repo_id = self.repo_id_combo.currentText().strip()
        if not repo_id:
            QMessageBox.warning(self, "Missing Repo ID", "Please enter a Repo ID first.")
            return

        self.fetch_revisions_btn.setEnabled(False)
        self.fetch_revisions_btn.setText("Fetching...")
        self.revision_combo.clear()

        from PyQt6.QtCore import QThread

        class _FetchRevisionsWorker(QThread):
            revisionsReady = pyqtSignal(list)
            fetchError = pyqtSignal(str)

            def __init__(self, repo_id: str, token: str | None) -> None:
                super().__init__()
                self._repo_id = repo_id
                self._token = token

            def run(self) -> None:
                try:
                    from huggingface_hub import HfApi
                    api = HfApi()
                    refs = api.list_repo_refs(self._repo_id, repo_type="dataset")
                    branch_names = [b.name for b in refs.branches] if hasattr(refs, "branches") and refs.branches else []
                    self.revisionsReady.emit(branch_names)
                except Exception as exc:
                    self.fetchError.emit(str(exc))

        self._fetch_worker = _FetchRevisionsWorker(repo_id, self.token_edit.text().strip() or None)
        self._fetch_worker.revisionsReady.connect(self._on_revisions_fetched)
        self._fetch_worker.fetchError.connect(self._on_revisions_fetch_error)
        self._fetch_worker.finished.connect(lambda: self._cleanup_fetch_worker())
        self._fetch_worker.start()

    def _on_revisions_fetched(self, branches: list) -> None:
        if not branches:
            QMessageBox.information(self, "No Revisions Found", "No branches found on this repository.")
        else:
            current = self.revision_combo.currentText()
            self.revision_combo.clear()
            # Sort branches: 'main' first, then alphabetically
            sorted_branches = sorted(branches, key=lambda x: (x != "main", x))
            self.revision_combo.addItems(sorted_branches)
            # Restore previous selection if it's still valid
            if current and current in branches:
                self.revision_combo.setCurrentText(current)
        self.fetch_revisions_btn.setEnabled(True)
        self.fetch_revisions_btn.setText("Fetch Revisions")

    def _on_revisions_fetch_error(self, error_msg: str) -> None:
        QMessageBox.warning(
            self,
            "Failed to Fetch Revisions",
            f"Could not fetch branches from Hugging Face.\n\nError:\n{error_msg}",
        )
        self.fetch_revisions_btn.setEnabled(True)
        self.fetch_revisions_btn.setText("Fetch Revisions")

    def _cleanup_fetch_worker(self) -> None:
        self._fetch_worker = None


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
