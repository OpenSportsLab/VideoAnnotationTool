import os
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QTreeView, QDialogButtonBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit, QHBoxLayout,
    QFrame, QListWidget, QComboBox, QPushButton, QLabel, QProgressBar,
    QMessageBox, QWidget, QListWidgetItem, QStyle, QButtonGroup, QScrollArea,
    QFileDialog, QCheckBox, QSizePolicy, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QPlainTextEdit, QKeySequenceEdit
)
from PyQt6.QtCore import QDir, Qt, QSize, QSettings, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QIcon, QKeySequence
from utils import get_square_remove_btn_style
from media_control_settings import (
    DEFAULT_PLAYBACK_FACTORS,
    DEFAULT_SEEK_INTERVALS,
    parse_playback_factors,
    parse_seek_intervals,
)
from inference_settings import (
    DEFAULT_SERVER_URL,
    KNOWN_HF_LOCAL_MODEL_IDS,
    SERVER_URL_KEY,
    load_local_models,
    load_shared_mappings,
    normalize_server_url,
    remote_inference_enabled,
    trusted_legacy_allowed,
)
from inference_types import INFERENCE_TASKS
from explorer_settings import (
    DEFAULT_EXPLORER_PAGE_SIZE,
    MAX_EXPLORER_PAGE_SIZE,
    MIN_EXPLORER_PAGE_SIZE,
    normalize_explorer_page_size,
)
from shortcut_settings import (
    DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT,
    DEFAULT_LOCALIZATION_REJECT_SHORTCUT,
    load_localization_review_shortcuts,
    validate_localization_review_shortcuts,
)


class HfLocalModelDialog(QDialog):
    """Collect the repository coordinates for a local model import."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Local Model from Hugging Face")
        self.setModal(True)
        self.resize(520, 180)
        root = QVBoxLayout(self)
        form = QFormLayout()
        root.addLayout(form)
        self.repository_combo = QComboBox(self)
        self.repository_combo.setEditable(True)
        self.repository_combo.addItems(KNOWN_HF_LOCAL_MODEL_IDS)
        self.repository_combo.setCurrentText("")
        self.repository_combo.setPlaceholderText("owner/model-name")
        form.addRow("Repository ID:", self.repository_combo)
        self.revision_edit = QLineEdit("main", self)
        form.addRow("Revision:", self.revision_edit)
        self.token_edit = QLineEdit(self)
        self.token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.token_edit.setPlaceholderText("Optional; blank uses HF login or HF_TOKEN")
        form.addRow("Token override:", self.token_edit)
        self.force_download_checkbox = QCheckBox(
            "Force re-download cached files", self
        )
        self.force_download_checkbox.setToolTip(
            "Re-fetch both the configuration and checkpoint even when they "
            "already exist in the Hugging Face cache."
        )
        form.addRow("", self.force_download_checkbox)
        note = QLabel(
            "The model configuration and checkpoint will be downloaded into the "
            "standard Hugging Face cache.",
            self,
        )
        note.setWordWrap(True)
        root.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def payload(self):
        repo_id = self.repository_combo.currentText().strip()
        revision = self.revision_edit.text().strip() or "main"
        if not repo_id or "/" not in repo_id or repo_id.startswith("/") or repo_id.endswith("/"):
            raise ValueError("Enter a repository ID such as owner/model-name.")
        return {
            "repo_id": repo_id,
            "revision": revision,
            "token": self.token_edit.text().strip() or None,
            "force_download": self.force_download_checkbox.isChecked(),
        }

    def _validate_and_accept(self):
        try:
            self.payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Hugging Face Model", str(exc))
            return
        self.accept()


class InferenceSetupWidget(QWidget):
    """Settings-only editor for Local models and one Remote server."""

    testConnectionRequested = pyqtSignal(object)
    remoteCatalogRefreshRequested = pyqtSignal(object)
    huggingFaceModelRequested = pyqtSignal(object)
    huggingFaceModelCancelRequested = pyqtSignal()
    configurationChanged = pyqtSignal()

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        config = dict(config or {})
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        local_group = QGroupBox("Local Models", self)
        local_layout = QVBoxLayout(local_group)
        self.local_model_table = QTableWidget(0, 5, local_group)
        self.local_model_table.setHorizontalHeaderLabels(["Task", "Model ID", "Display name", "Config YAML", "Weights"])
        self.local_model_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        local_layout.addWidget(self.local_model_table)
        model_buttons = QHBoxLayout()
        self.add_local_model_button = QPushButton("Add Manually", local_group)
        self.add_hf_model_button = QPushButton("Add from Hugging Face…", local_group)
        self.remove_local_model_button = QPushButton("Remove Local Model", local_group)
        model_buttons.addWidget(self.add_local_model_button)
        model_buttons.addWidget(self.add_hf_model_button)
        model_buttons.addWidget(self.remove_local_model_button)
        model_buttons.addStretch(1)
        local_layout.addLayout(model_buttons)
        transfer_row = QHBoxLayout()
        self.local_model_status = QLabel("", local_group)
        self.local_model_status.setWordWrap(True)
        self.local_model_progress = QProgressBar(local_group)
        self.local_model_progress.setRange(0, 3)
        self.local_model_progress.hide()
        self.cancel_hf_model_button = QPushButton("Cancel Download", local_group)
        self.cancel_hf_model_button.hide()
        transfer_row.addWidget(self.local_model_status, 1)
        transfer_row.addWidget(self.local_model_progress)
        transfer_row.addWidget(self.cancel_hf_model_button)
        local_layout.addLayout(transfer_row)
        root.addWidget(local_group)

        self.remote_group = QGroupBox("Remote Server", self)
        remote_layout = QVBoxLayout(self.remote_group)
        self.remote_enabled_checkbox = QCheckBox("Enable remote inference", self.remote_group)
        self.remote_enabled_checkbox.setChecked(bool(config.get("remote_enabled", False)))
        remote_layout.addWidget(self.remote_enabled_checkbox)
        remote_form = QFormLayout()
        remote_layout.addLayout(remote_form)
        server_row = QWidget(self.remote_group)
        server_layout = QHBoxLayout(server_row)
        server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_url_edit = QLineEdit(str(config.get("server_url") or DEFAULT_SERVER_URL), server_row)
        self.test_button = QPushButton("Test Connection", server_row)
        self.refresh_remote_models_button = QPushButton("Refresh Models", server_row)
        server_layout.addWidget(self.server_url_edit, 1)
        server_layout.addWidget(self.test_button)
        server_layout.addWidget(self.refresh_remote_models_button)
        remote_form.addRow("Server URL:", server_row)
        self.connection_status = QLabel("", self.remote_group)
        self.connection_status.setWordWrap(True)
        remote_layout.addWidget(self.connection_status)

        remote_layout.addWidget(QLabel("Discovered remote models", self.remote_group))
        self.remote_model_table = QTableWidget(0, 3, self.remote_group)
        self.remote_model_table.setHorizontalHeaderLabels(["Task", "Model ID", "Display name"])
        self.remote_model_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.remote_model_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        remote_layout.addWidget(self.remote_model_table)

        remote_layout.addWidget(QLabel("Shared storage mappings", self.remote_group))
        self.mapping_table = QTableWidget(0, 2, self.remote_group)
        self.mapping_table.setHorizontalHeaderLabels(["Local directory", "Server root ID"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        remote_layout.addWidget(self.mapping_table)
        mapping_buttons = QHBoxLayout()
        self.add_mapping_button = QPushButton("Add Mapping", self.remote_group)
        self.remove_mapping_button = QPushButton("Remove Mapping", self.remote_group)
        mapping_buttons.addWidget(self.add_mapping_button)
        mapping_buttons.addWidget(self.remove_mapping_button)
        mapping_buttons.addStretch(1)
        remote_layout.addLayout(mapping_buttons)
        root.addWidget(self.remote_group)

        for mapping in config.get("shared_mappings", []):
            self.append_mapping(mapping.get("local_root", ""), mapping.get("root_id", ""))
        for model in config.get("local_models", []):
            self.append_local_model(model)
        self.add_mapping_button.clicked.connect(lambda: self.append_mapping("", ""))
        self.remove_mapping_button.clicked.connect(lambda: self._remove_row(self.mapping_table))
        self.add_local_model_button.clicked.connect(lambda: self.append_local_model({"task": "classification"}))
        self.add_hf_model_button.clicked.connect(self._request_hf_model)
        self.cancel_hf_model_button.clicked.connect(self.huggingFaceModelCancelRequested)
        self.remove_local_model_button.clicked.connect(lambda: self._remove_row(self.local_model_table))
        self.test_button.clicked.connect(lambda: self.testConnectionRequested.emit(self.payload()))
        self.refresh_remote_models_button.clicked.connect(
            lambda: self.remoteCatalogRefreshRequested.emit(self.payload())
        )
        self.remote_enabled_checkbox.toggled.connect(self._update_remote_enabled)
        self.server_url_edit.textChanged.connect(self._changed)
        self._update_remote_enabled()
        self._changed()

    def _update_remote_enabled(self, *_args):
        enabled = self.remote_enabled_checkbox.isChecked()
        for widget in (
            self.server_url_edit,
            self.test_button,
            self.refresh_remote_models_button,
            self.remote_model_table,
            self.mapping_table,
            self.add_mapping_button,
            self.remove_mapping_button,
        ):
            widget.setEnabled(enabled)
        self._changed()

    def _changed(self, *_args):
        self.connection_status.clear()
        parsed = urlparse(self.server_url_edit.text().strip())
        if (
            self.remote_enabled_checkbox.isChecked()
            and parsed.scheme == "http"
            and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            self.set_connection_status(
                "Warning: this endpoint is unauthenticated and unencrypted; use only a trusted network.",
                False,
            )
        self.configurationChanged.emit()

    @staticmethod
    def _remove_row(table):
        if table.currentRow() >= 0:
            table.removeRow(table.currentRow())

    def append_mapping(self, local_root, root_id):
        row = self.mapping_table.rowCount()
        self.mapping_table.insertRow(row)
        self.mapping_table.setItem(row, 0, QTableWidgetItem(str(local_root or "")))
        self.mapping_table.setItem(row, 1, QTableWidgetItem(str(root_id or "")))

    def append_local_model(self, model):
        row = self.local_model_table.rowCount()
        self.local_model_table.insertRow(row)
        self._set_local_model_row(row, model)

    def _set_local_model_row(self, row, model):
        values = (
            model.get("task", "classification"),
            model.get("id", ""),
            model.get("display_name", ""),
            model.get("config_path", ""),
            model.get("weights", ""),
        )
        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value or ""))
            if column == 0:
                metadata = dict(model)
                metadata["_registry_source"] = {
                    "id": str(model.get("id") or ""),
                    "hf_repo_id": str(model.get("hf_repo_id") or ""),
                    "hf_revision": str(model.get("hf_revision") or ""),
                    "weights": str(model.get("weights") or ""),
                }
                item.setData(Qt.ItemDataRole.UserRole, metadata)
            self.local_model_table.setItem(row, column, item)

    def upsert_local_model(self, model):
        key = (str(model.get("task") or ""), str(model.get("id") or ""))
        for row in range(self.local_model_table.rowCount()):
            current = tuple(
                str(self.local_model_table.item(row, col).text() if self.local_model_table.item(row, col) else "").strip()
                for col in (0, 1)
            )
            if current == key:
                self.local_model_table.removeRow(row)
                self.local_model_table.insertRow(row)
                self._set_local_model_row(row, model)
                self.local_model_table.selectRow(row)
                return
        self.append_local_model(model)
        self.local_model_table.selectRow(self.local_model_table.rowCount() - 1)

    def _request_hf_model(self):
        dialog = HfLocalModelDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.huggingFaceModelRequested.emit(dialog.payload())

    def set_model_import_busy(self, busy, message=""):
        busy = bool(busy)
        self.add_hf_model_button.setEnabled(not busy)
        self.local_model_progress.setVisible(busy)
        self.cancel_hf_model_button.setVisible(busy)
        if message:
            self.local_model_status.setText(str(message))

    def set_model_import_progress(self, message, current=0, total=0):
        self.local_model_status.setText(str(message or ""))
        if total > 0:
            self.local_model_progress.setRange(0, int(total))
            self.local_model_progress.setValue(max(0, min(int(current), int(total))))
        else:
            self.local_model_progress.setRange(0, 0)

    def set_connection_status(self, text, success):
        self.connection_status.setText(str(text or ""))
        self.connection_status.setStyleSheet("color: #27823b;" if success else "color: #d9534f;")

    def set_remote_catalog(self, models):
        self.remote_model_table.setRowCount(0)
        for descriptor in list(models or []):
            row = self.remote_model_table.rowCount()
            self.remote_model_table.insertRow(row)
            for column, value in enumerate(
                (descriptor.task, descriptor.id, descriptor.display_name)
            ):
                self.remote_model_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.set_connection_status(
            f"Discovered {self.remote_model_table.rowCount()} remote model(s).",
            True,
        )

    def payload(self):
        mappings = []
        for row in range(self.mapping_table.rowCount()):
            values = [str(self.mapping_table.item(row, col).text() if self.mapping_table.item(row, col) else "").strip() for col in range(2)]
            if bool(values[0]) != bool(values[1]):
                raise ValueError("Each shared mapping requires both a local directory and server root ID.")
            if values[0]:
                mappings.append({"local_root": os.path.abspath(os.path.expanduser(values[0])), "root_id": values[1]})
        models = []
        for row in range(self.local_model_table.rowCount()):
            values = [str(self.local_model_table.item(row, col).text() if self.local_model_table.item(row, col) else "").strip() for col in range(5)]
            if not any(values):
                continue
            task, model_id, display_name, config_path, weights = values
            if task not in INFERENCE_TASKS or not model_id or not config_path:
                raise ValueError("Each local model requires a valid task, model ID, and config YAML path.")
            first_item = self.local_model_table.item(row, 0)
            metadata = first_item.data(Qt.ItemDataRole.UserRole) if first_item else None
            model = dict(metadata if isinstance(metadata, dict) else {})
            source = dict(model.pop("_registry_source", {}) or {})
            model.update({
                "task": task,
                "id": model_id,
                "display_name": display_name or model_id,
                "config_path": config_path,
                "weights": weights,
                "available": True,
                "accepted_input_types": ["video"],
                "supports_time_range": task in {"localization", "dense_description"},
            })
            if source and any(
                (
                    model_id != source.get("id", ""),
                    str(model.get("hf_repo_id") or "") != source.get("hf_repo_id", ""),
                    str(model.get("hf_revision") or "") != source.get("hf_revision", ""),
                    weights != source.get("weights", ""),
                )
            ):
                model["trusted_legacy"] = False
            model["trusted_legacy"] = trusted_legacy_allowed(model)
            models.append(model)
        return {
            "remote_enabled": self.remote_enabled_checkbox.isChecked(),
            "server_url": normalize_server_url(self.server_url_edit.text()),
            "shared_mappings": mappings,
            "local_models": models,
        }


class ApplicationSettingsDialog(QDialog):
    """Extensible application settings dialog."""

    mediaControlsApplyRequested = pyqtSignal(str, str, object, object)
    inferenceSettingsApplyRequested = pyqtSignal(object)
    inferenceTestRequested = pyqtSignal()
    inferenceRemoteCatalogRequested = pyqtSignal()
    inferenceHfModelRequested = pyqtSignal(object)
    inferenceHfModelCancelRequested = pyqtSignal()
    explorerPageSizeApplyRequested = pyqtSignal(int)
    shortcutSettingsApplyRequested = pyqtSignal(str, str)

    def __init__(
        self,
        playback_factors: str,
        seek_intervals: str,
        explorer_page_size: int = DEFAULT_EXPLORER_PAGE_SIZE,
        settings: QSettings | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(520, 260)

        root_layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        root_layout.addWidget(tabs)

        media_page = QWidget(tabs)
        media_layout = QVBoxLayout(media_page)
        form = QFormLayout()
        media_layout.addLayout(form)

        self.playback_factors_edit = QLineEdit(str(playback_factors), media_page)
        self.playback_factors_edit.setObjectName("playbackFactorsEdit")
        self.playback_factors_edit.setPlaceholderText(DEFAULT_PLAYBACK_FACTORS)
        self.playback_factors_edit.setToolTip(
            "Comma-separated positive factors. Each factor adds its direct and reciprocal speed."
        )
        form.addRow("Playback speed factors:", self.playback_factors_edit)

        self.seek_intervals_edit = QLineEdit(str(seek_intervals), media_page)
        self.seek_intervals_edit.setObjectName("seekIntervalsEdit")
        self.seek_intervals_edit.setPlaceholderText(DEFAULT_SEEK_INTERVALS)
        self.seek_intervals_edit.setToolTip("Comma-separated positive seek intervals in seconds.")
        form.addRow("Seek intervals (seconds):", self.seek_intervals_edit)

        help_label = QLabel(
            "Examples: speed factors 2,4 create 0.25x through 4x; "
            "seek intervals 1,5 create matching backward and forward buttons.",
            media_page,
        )
        help_label.setWordWrap(True)
        media_layout.addWidget(help_label)

        self.validation_label = QLabel("", media_page)
        self.validation_label.setObjectName("settingsValidationLabel")
        self.validation_label.setWordWrap(True)
        self.validation_label.setStyleSheet("color: #d9534f;")
        media_layout.addWidget(self.validation_label)
        media_layout.addStretch(1)
        tabs.addTab(media_page, "Media Controls")

        explorer_page = QWidget(tabs)
        explorer_layout = QVBoxLayout(explorer_page)
        explorer_form = QFormLayout()
        explorer_layout.addLayout(explorer_form)
        self.explorer_page_size_spin = QSpinBox(explorer_page)
        self.explorer_page_size_spin.setObjectName("explorerPageSizeSpin")
        self.explorer_page_size_spin.setRange(
            MIN_EXPLORER_PAGE_SIZE,
            MAX_EXPLORER_PAGE_SIZE,
        )
        self.explorer_page_size_spin.setSingleStep(100)
        self.explorer_page_size_spin.setValue(
            normalize_explorer_page_size(explorer_page_size)
        )
        self.explorer_page_size_spin.setSuffix(" samples")
        explorer_form.addRow("Samples per page:", self.explorer_page_size_spin)
        explorer_help = QLabel(
            "Controls the maximum number of top-level samples shown in the "
            "Dataset Explorer. Smaller pages reduce view work for very large datasets.",
            explorer_page,
        )
        explorer_help.setWordWrap(True)
        explorer_layout.addWidget(explorer_help)
        explorer_layout.addStretch(1)
        tabs.addTab(explorer_page, "Dataset Explorer")

        shortcut_page = QWidget(tabs)
        shortcut_layout = QVBoxLayout(shortcut_page)
        shortcut_form = QFormLayout()
        shortcut_layout.addLayout(shortcut_form)
        review_shortcuts = load_localization_review_shortcuts(settings)
        self.localization_accept_shortcut_edit = QKeySequenceEdit(
            QKeySequence(review_shortcuts.accept), shortcut_page
        )
        self.localization_accept_shortcut_edit.setObjectName(
            "localizationAcceptShortcutEdit"
        )
        shortcut_form.addRow(
            "Accept selected localization prediction:",
            self.localization_accept_shortcut_edit,
        )
        self.localization_reject_shortcut_edit = QKeySequenceEdit(
            QKeySequence(review_shortcuts.reject), shortcut_page
        )
        self.localization_reject_shortcut_edit.setObjectName(
            "localizationRejectShortcutEdit"
        )
        shortcut_form.addRow(
            "Reject selected localization prediction:",
            self.localization_reject_shortcut_edit,
        )
        shortcut_help = QLabel(
            "These shortcuts work only while Localization is the active annotation editor. "
            "They require a selected row with a confidence score.",
            shortcut_page,
        )
        shortcut_help.setWordWrap(True)
        shortcut_layout.addWidget(shortcut_help)
        self.shortcut_validation_label = QLabel("", shortcut_page)
        self.shortcut_validation_label.setObjectName("shortcutValidationLabel")
        self.shortcut_validation_label.setWordWrap(True)
        self.shortcut_validation_label.setStyleSheet("color: #d9534f;")
        shortcut_layout.addWidget(self.shortcut_validation_label)
        shortcut_layout.addStretch(1)
        tabs.addTab(shortcut_page, "Shortcuts")

        self._settings = settings
        inference_page = QWidget(tabs)
        inference_layout = QVBoxLayout(inference_page)
        inference_config = {
            "remote_enabled": remote_inference_enabled(settings),
            "server_url": str(settings.value(SERVER_URL_KEY, DEFAULT_SERVER_URL) if settings is not None else DEFAULT_SERVER_URL),
            "shared_mappings": load_shared_mappings(settings),
            "local_models": load_local_models(settings),
        }
        self.inference_setup_widget = InferenceSetupWidget(inference_config, parent=inference_page)
        inference_layout.addWidget(self.inference_setup_widget)
        self.inference_remote_enabled_checkbox = self.inference_setup_widget.remote_enabled_checkbox
        self.inference_server_url_edit = self.inference_setup_widget.server_url_edit
        self.inference_test_button = self.inference_setup_widget.test_button
        self.inference_refresh_models_button = self.inference_setup_widget.refresh_remote_models_button
        self.inference_connection_status = self.inference_setup_widget.connection_status
        self.remote_model_table = self.inference_setup_widget.remote_model_table
        self.shared_mapping_table = self.inference_setup_widget.mapping_table
        self.local_model_table = self.inference_setup_widget.local_model_table
        self.add_mapping_button = self.inference_setup_widget.add_mapping_button
        self.remove_mapping_button = self.inference_setup_widget.remove_mapping_button
        self.add_local_model_button = self.inference_setup_widget.add_local_model_button
        self.add_hf_model_button = self.inference_setup_widget.add_hf_model_button
        self.remove_local_model_button = self.inference_setup_widget.remove_local_model_button

        tabs.addTab(inference_page, "Inference")
        self.resize(760, 620)

        self.buttons = QDialogButtonBox(self)
        self.restore_defaults_button = self.buttons.addButton(
            "Restore Defaults", QDialogButtonBox.ButtonRole.ResetRole
        )
        self.apply_button = self.buttons.addButton(
            QDialogButtonBox.StandardButton.Apply
        )
        self.ok_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Ok)
        self.cancel_button = self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        root_layout.addWidget(self.buttons)

        self.restore_defaults_button.clicked.connect(self._restore_defaults)
        self.apply_button.clicked.connect(lambda: self._apply(close_after=False))
        self.ok_button.clicked.connect(lambda: self._apply(close_after=True))
        self.cancel_button.clicked.connect(self.reject)
        self.playback_factors_edit.textChanged.connect(lambda _text: self.validation_label.clear())
        self.seek_intervals_edit.textChanged.connect(lambda _text: self.validation_label.clear())
        self.localization_accept_shortcut_edit.keySequenceChanged.connect(
            lambda _sequence: self.shortcut_validation_label.clear()
        )
        self.localization_reject_shortcut_edit.keySequenceChanged.connect(
            lambda _sequence: self.shortcut_validation_label.clear()
        )
        self.inference_setup_widget.testConnectionRequested.connect(lambda _config: self.inferenceTestRequested.emit())
        self.inference_setup_widget.remoteCatalogRefreshRequested.connect(
            lambda _config: self.inferenceRemoteCatalogRequested.emit()
        )
        self.inference_setup_widget.huggingFaceModelRequested.connect(
            self.inferenceHfModelRequested
        )
        self.inference_setup_widget.huggingFaceModelCancelRequested.connect(
            self.inferenceHfModelCancelRequested
        )

    def _append_mapping(self, local_root: str, root_id: str):
        self.inference_setup_widget.append_mapping(local_root, root_id)

    def _remove_selected_mapping(self):
        row = self.shared_mapping_table.currentRow()
        if row >= 0:
            self.shared_mapping_table.removeRow(row)

    def _append_local_model(self, model: dict):
        self.inference_setup_widget.append_local_model(model)

    def _remove_selected_local_model(self):
        row = self.local_model_table.currentRow()
        if row >= 0:
            self.local_model_table.removeRow(row)

    def set_inference_connection_status(self, text: str, success: bool):
        self.inference_setup_widget.set_connection_status(text, success)

    def set_remote_model_catalog(self, models):
        self.inference_setup_widget.set_remote_catalog(models)

    def set_hf_model_import_busy(self, busy, message=""):
        self.inference_setup_widget.set_model_import_busy(busy, message)
        self.apply_button.setEnabled(not busy)
        self.ok_button.setEnabled(not busy)
        self.restore_defaults_button.setEnabled(not busy)

    def set_hf_model_import_progress(self, message, current=0, total=0):
        self.inference_setup_widget.set_model_import_progress(message, current, total)

    def add_downloaded_hf_model(self, model):
        self.inference_setup_widget.upsert_local_model(model)
        self.set_hf_model_import_busy(
            False, f"Added {model.get('id', 'model')} to this Settings draft."
        )

    def inference_payload(self) -> dict:
        return self.inference_setup_widget.payload()

    def _restore_defaults(self) -> None:
        self.playback_factors_edit.setText(DEFAULT_PLAYBACK_FACTORS)
        self.seek_intervals_edit.setText(DEFAULT_SEEK_INTERVALS)
        self.explorer_page_size_spin.setValue(DEFAULT_EXPLORER_PAGE_SIZE)
        self.localization_accept_shortcut_edit.setKeySequence(
            QKeySequence(DEFAULT_LOCALIZATION_ACCEPT_SHORTCUT)
        )
        self.localization_reject_shortcut_edit.setKeySequence(
            QKeySequence(DEFAULT_LOCALIZATION_REJECT_SHORTCUT)
        )
        self.inference_remote_enabled_checkbox.setChecked(False)
        self.inference_server_url_edit.setText(DEFAULT_SERVER_URL)
        self.shared_mapping_table.setRowCount(0)
        self.local_model_table.setRowCount(0)
        self.remote_model_table.setRowCount(0)
        self.validation_label.clear()
        self.shortcut_validation_label.clear()

    def _apply(self, *, close_after: bool) -> None:
        try:
            factors = parse_playback_factors(self.playback_factors_edit.text())
            intervals = parse_seek_intervals(self.seek_intervals_edit.text())
            inference_payload = self.inference_payload()
        except ValueError as exc:
            self.validation_label.setText(str(exc))
            return

        try:
            shortcuts = validate_localization_review_shortcuts(
                self.localization_accept_shortcut_edit.keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText
                ),
                self.localization_reject_shortcut_edit.keySequence().toString(
                    QKeySequence.SequenceFormat.PortableText
                ),
            )
        except ValueError as exc:
            self.shortcut_validation_label.setText(str(exc))
            return

        self.playback_factors_edit.setText(factors.normalized_text)
        self.seek_intervals_edit.setText(intervals.normalized_text)
        self.validation_label.clear()
        self.mediaControlsApplyRequested.emit(
            factors.normalized_text,
            intervals.normalized_text,
            factors.values,
            intervals.values,
        )
        self.shortcutSettingsApplyRequested.emit(shortcuts.accept, shortcuts.reject)
        self.inferenceSettingsApplyRequested.emit(inference_payload)
        parsed_server = urlparse(inference_payload["server_url"])
        if (
            inference_payload["remote_enabled"]
            and parsed_server.scheme == "http"
            and parsed_server.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            self.set_inference_connection_status(
                "Warning: this server is unauthenticated and unencrypted. Use it only on a trusted network.",
                False,
            )
        self.explorerPageSizeApplyRequested.emit(self.explorer_page_size_spin.value())
        if close_after:
            self.accept()


class InferenceRunDialog(QDialog):
    """Reusable task-aware model and input selection dialog."""

    refreshModelsRequested = pyqtSignal(str)

    def __init__(
        self,
        task: str,
        inputs: list,
        context: dict | None = None,
        *,
        preferred_model=None,
        parent=None,
    ):
        super().__init__(parent)
        self.task = str(task)
        self.inputs = list(inputs or [])
        self.context = dict(context or {})
        self.preferred_model = tuple(preferred_model) if preferred_model else None
        self.setWindowTitle("Run Inference")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.runtime_form = form
        layout.addLayout(form)

        model_row = QWidget(self)
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox(model_row)
        self.refresh_models_button = QPushButton("Refresh", model_row)
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(self.refresh_models_button)
        form.addRow("Model:", model_row)

        self.start_spin = QSpinBox(self)
        self.start_spin.setRange(0, 2_147_483_647)
        self.start_spin.setValue(int(self.context.get("start_ms", 0) or 0))
        self.end_spin = QSpinBox(self)
        self.end_spin.setRange(0, 2_147_483_647)
        self.end_spin.setValue(int(self.context.get("end_ms", 0) or 0))
        if self.task in {"localization", "dense_description"}:
            form.addRow("Start (ms):", self.start_spin)
            form.addRow("End (ms, 0 = end):", self.end_spin)
            form.setRowVisible(self.start_spin, False)
            form.setRowVisible(self.end_spin, False)

        self.language_edit = QLineEdit(str(self.context.get("language") or "en"), self)
        if self.task in {"description", "dense_description"}:
            form.addRow("Language:", self.language_edit)

        self.question_edit = QPlainTextEdit(self)
        self.question_edit.setPlainText(str(self.context.get("question") or ""))
        self.question_edit.setMaximumHeight(90)
        if self.task == "question_answer":
            form.addRow("Question:", self.question_edit)

        layout.addWidget(QLabel("Inputs", self))
        self.input_list = QListWidget(self)
        for source in self.inputs:
            label = os.path.basename(str(getattr(source, "path", "") or "")) or str(getattr(source, "path", ""))
            item = QListWidgetItem(label, self.input_list)
            item.setData(Qt.ItemDataRole.UserRole, source)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
        layout.addWidget(self.input_list, 1)

        self.availability_label = QLabel("", self)
        self.availability_label.setWordWrap(True)
        layout.addWidget(self.availability_label)
        self.run_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.run_buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        layout.addWidget(self.run_buttons)

        self.run_buttons.accepted.connect(self._accept_if_valid)
        self.run_buttons.rejected.connect(self.reject)
        self.refresh_models_button.clicked.connect(self._request_refresh)
        self.model_combo.currentIndexChanged.connect(self._update_model_availability)

        self.scope_combo = None
        if self.task == "classification" and self.context.get("available_batch_sample_ids"):
            self.scope_combo = QComboBox(self)
            self.scope_combo.addItem("Current sample", "current")
            self.scope_combo.addItem("All samples", "all")
            form.insertRow(1, "Scope:", self.scope_combo)
            self.scope_combo.currentIndexChanged.connect(self._apply_scope)
            self._apply_scope()

    def _apply_scope(self, *_args):
        if self.scope_combo is None:
            return
        current_only = self.scope_combo.currentData() == "current"
        current_id = str(self.context.get("current_sample_id") or "")
        for index in range(self.input_list.count()):
            item = self.input_list.item(index)
            source = item.data(Qt.ItemDataRole.UserRole)
            sample_id = str(getattr(source, "sample_id", "") or "")
            item.setCheckState(Qt.CheckState.Checked if not current_only or sample_id == current_id else Qt.CheckState.Unchecked)

    def _request_refresh(self):
        self.refreshModelsRequested.emit(self.task)

    def set_models(self, choices, warning: str = ""):
        current = self.model_combo.currentData()
        previous = current.key if current is not None else self.preferred_model
        self.model_combo.clear()
        for choice in list(choices or []):
            self.model_combo.addItem(choice.display_name, choice)
        if previous:
            for index in range(self.model_combo.count()):
                choice = self.model_combo.itemData(index)
                if choice is not None and choice.key == tuple(previous):
                    self.model_combo.setCurrentIndex(index)
                    break
        self._catalog_warning = str(warning or "")
        self._update_model_availability()

    def _update_model_availability(self):
        choice = self.model_combo.currentData()
        descriptor = choice.descriptor if choice is not None else None
        available = descriptor is not None
        message = getattr(self, "_catalog_warning", "")
        if descriptor is None:
            message = "No runnable models are configured for this task. " + message
        self.availability_label.setText(message)
        self.run_buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(available)
        # Don't disable inputs by guessing compatibility from accepted_input_types:
        # it's only a hint recorded at import time and isn't reliable enough to
        # gate what the user can select (e.g. a rule-based model imported from
        # Hugging Face is always labeled "video" even when it actually needs
        # something else). Leave every input selectable and let the run itself
        # report a real error if the inputs don't fit.
        for index in range(self.input_list.count()):
            item = self.input_list.item(index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
        supports_range = bool(descriptor is not None and descriptor.supports_time_range)
        if self.task in {"localization", "dense_description"}:
            self.runtime_form.setRowVisible(self.start_spin, supports_range)
            self.runtime_form.setRowVisible(self.end_spin, supports_range)

    def _accept_if_valid(self):
        selected_inputs = self.selected_inputs()
        if not selected_inputs:
            self.availability_label.setText("Select at least one input.")
            return
        choice = self.model_combo.currentData()
        descriptor = choice.descriptor if choice is not None else None
        is_batch = bool(self.context.get("batch_sample_ids")) or bool(self.scope_combo is not None and self.scope_combo.currentData() == "all")
        if descriptor is not None and not is_batch:
            if len(selected_inputs) < descriptor.min_inputs:
                self.availability_label.setText(f"This model requires at least {descriptor.min_inputs} input(s).")
                return
            if descriptor.max_inputs is not None and len(selected_inputs) > descriptor.max_inputs:
                self.availability_label.setText(f"This model accepts at most {descriptor.max_inputs} input(s).")
                return
        elif descriptor is not None and is_batch:
            counts = {}
            for source in selected_inputs:
                sample_id = str(getattr(source, "sample_id", "") or "")
                counts[sample_id] = counts.get(sample_id, 0) + 1
            if any(count < descriptor.min_inputs for count in counts.values()):
                self.availability_label.setText(f"Every sample requires at least {descriptor.min_inputs} input(s).")
                return
            if descriptor.max_inputs is not None and any(count > descriptor.max_inputs for count in counts.values()):
                self.availability_label.setText(f"Every sample accepts at most {descriptor.max_inputs} input(s).")
                return
        if self.task == "question_answer" and not self.question_edit.toPlainText().strip():
            self.availability_label.setText("Enter a question.")
            return
        if (
            descriptor is not None
            and descriptor.supports_time_range
            and self.end_spin.value()
            and self.end_spin.value() <= self.start_spin.value()
        ):
            self.availability_label.setText("End time must be greater than start time.")
            return
        self.accept()

    def selected_inputs(self):
        selected = []
        for index in range(self.input_list.count()):
            item = self.input_list.item(index)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.data(Qt.ItemDataRole.UserRole))
        return selected

    def payload(self) -> dict:
        choice = self.model_combo.currentData()
        supports_range = bool(
            choice is not None and choice.descriptor.supports_time_range
        )
        return {
            "backend": choice.backend if choice is not None else "",
            "model_id": choice.descriptor.id if choice is not None else "",
            "inputs": self.selected_inputs(),
            "start_ms": self.start_spin.value() if supports_range else 0,
            "end_ms": self.end_spin.value() if supports_range else 0,
            "language": self.language_edit.text().strip() or "en",
            "question": self.question_edit.toPlainText().strip(),
            "scope": str(self.scope_combo.currentData()) if self.scope_combo is not None else "current",
        }

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
    _KEY_SPLITS = f"{_SETTINGS_PREFIX}/splits"
    _KEY_SUCCESS_TRANSFERS = f"{_SETTINGS_PREFIX}/successful_transfers"
    _KEY_SUCCESS_URLS = f"{_SETTINGS_PREFIX}/successful_urls"
    _KEY_OUTPUT_DIR = f"{_SETTINGS_PREFIX}/output_dir"
    _KEY_DRY_RUN = f"{_SETTINGS_PREFIX}/dry_run"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"
    _AVAILABLE_DATASET_TRANSFERS = [
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "test"},
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "valid"},
        {"repo_id": "OpenSportsLab/OSL-XFoul", "revision": "main-parquet", "split": "train"},
        {"repo_id": "OpenSportsLab/soccernetpro-classification-vars", "revision": "mvfouls", "split": "annotations_test"},
    ]
    _FORMAT_LABELS = {
        "parquet": "Format: Parquet + WebDataset",
        "json": "Format: JSON + referenced inputs",
        None: "Format: unknown (fetch splits to detect)",
    }

    def __init__(self, settings: QSettings | None = None, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._submitted = False
        self._detected_format: str | None = None
        self._branches_worker = None
        self._splits_worker = None
        self.setWindowTitle("Download Dataset from Hugging Face")
        self.setModal(True)
        self.setMinimumWidth(760)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        layout.addLayout(form)

        self.repo_id_edit = QLineEdit(self)
        self.repo_id_edit.setPlaceholderText("OpenSportsLab/OSL-XFoul")
        form.addRow("Repo ID*", self.repo_id_edit)

        self.revision_combo = QComboBox(self)
        self.revision_combo.setEditable(True)
        self.revision_combo.addItem("main")
        self.fetch_branches_button = QPushButton("Fetch Branches", self)
        self.fetch_branches_button.clicked.connect(self._fetch_branches)
        branch_row = QHBoxLayout()
        branch_row.addWidget(self.revision_combo, 1)
        branch_row.addWidget(self.fetch_branches_button, 0)
        form.addRow("Branch*", branch_row)

        self.split_list = QListWidget(self)
        self.split_list.setMaximumHeight(120)
        self.fetch_splits_button = QPushButton("Fetch Splits", self)
        self.fetch_splits_button.clicked.connect(self._fetch_splits)
        self.detected_format_label = QLabel(self._FORMAT_LABELS[None], self)
        split_column = QVBoxLayout()
        split_column.addWidget(self.split_list)
        split_row = QHBoxLayout()
        split_row.addWidget(self.fetch_splits_button, 0)
        split_row.addWidget(self.detected_format_label, 1)
        split_column.addLayout(split_row)
        form.addRow("Split(s)*", split_column)

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

        self.revision_combo.setMinimumHeight(34)
        self.revision_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for edit in (self.repo_id_edit, self.output_dir_edit, self.token_edit):
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
    def _normalize_transfer(cls, transfer: dict | None) -> dict:
        payload = transfer if isinstance(transfer, dict) else {}
        return {
            "repo_id": str(payload.get("repo_id") or "").strip(),
            "revision": str(payload.get("revision") or "main").strip() or "main",
            "split": str(payload.get("split") or "").strip(),
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
            ]
        )

    @classmethod
    def _transfer_from_key(cls, key: str) -> dict:
        parts = str(key or "").split("|")
        if len(parts) != 3:
            return {}
        return cls._normalize_transfer(
            {
                "repo_id": parts[0],
                "revision": parts[1],
                "split": parts[2],
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

    def _checked_splits(self) -> list[str]:
        checked = []
        for row in range(self.split_list.count()):
            item = self.split_list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                checked.append(item.text())
        return checked

    def _fetch_branches(self) -> None:
        repo_id = self.repo_id_edit.text().strip()
        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required before fetching branches.")
            return
        if self._branches_worker and self._branches_worker.isRunning():
            return

        from controllers.hf_transfer_controller import _HfListBranchesWorker

        self.fetch_branches_button.setEnabled(False)
        self.fetch_branches_button.setText("Fetching…")
        token = self.token_edit.text().strip() or None
        worker = _HfListBranchesWorker(repo_id, token)
        self._branches_worker = worker
        worker.succeeded.connect(self._on_branches_fetched)
        worker.failed.connect(self._on_branches_fetch_failed)
        worker.finished.connect(lambda: self._cleanup_branches_worker(worker))
        worker.start()

    def _cleanup_branches_worker(self, worker) -> None:
        if self._branches_worker is worker:
            self._branches_worker = None
        self.fetch_branches_button.setEnabled(True)
        self.fetch_branches_button.setText("Fetch Branches")
        worker.deleteLater()

    def _on_branches_fetched(self, branches: list) -> None:
        current_text = self.revision_combo.currentText().strip()
        self.revision_combo.clear()
        self.revision_combo.addItems(branches)
        if current_text and self.revision_combo.findText(current_text) < 0:
            self.revision_combo.addItem(current_text)
        if current_text:
            self.revision_combo.setCurrentText(current_text)
        elif branches:
            self.revision_combo.setCurrentIndex(0)
        if not branches:
            QMessageBox.information(self, "No Branches Found", "No branches were found for this repository.")

    def _on_branches_fetch_failed(self, error: str) -> None:
        QMessageBox.warning(self, "Fetch Branches Failed", error)

    def _fetch_splits(self) -> None:
        repo_id = self.repo_id_edit.text().strip()
        revision = self.revision_combo.currentText().strip()
        if not repo_id or not revision:
            QMessageBox.warning(
                self,
                "Missing Required Field",
                "Repo ID and Branch are required before fetching splits.",
            )
            return
        if self._splits_worker and self._splits_worker.isRunning():
            return

        from controllers.hf_transfer_controller import _HfListSplitsWorker

        self.fetch_splits_button.setEnabled(False)
        self.fetch_splits_button.setText("Fetching…")
        token = self.token_edit.text().strip() or None
        worker = _HfListSplitsWorker(repo_id, revision, token)
        self._splits_worker = worker
        worker.succeeded.connect(self._on_splits_fetched)
        worker.failed.connect(self._on_splits_fetch_failed)
        worker.finished.connect(lambda: self._cleanup_splits_worker(worker))
        worker.start()

    def _cleanup_splits_worker(self, worker) -> None:
        if self._splits_worker is worker:
            self._splits_worker = None
        self.fetch_splits_button.setEnabled(True)
        self.fetch_splits_button.setText("Fetch Splits")
        worker.deleteLater()

    def _on_splits_fetched(self, result: dict) -> None:
        splits = list(result.get("splits") or [])
        self._detected_format = result.get("format")
        self.detected_format_label.setText(self._FORMAT_LABELS.get(self._detected_format, self._FORMAT_LABELS[None]))

        self.split_list.clear()
        if not splits:
            QMessageBox.information(
                self, "No Splits Found", "No JSON or Parquet/WebDataset splits were found for this branch."
            )
            return

        preselect = self._last_selected_splits & set(splits) if self._last_selected_splits else set(splits)
        for split in splits:
            item = QListWidgetItem(split)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if split in preselect else Qt.CheckState.Unchecked)
            self.split_list.addItem(item)

    def _on_splits_fetch_failed(self, error: str) -> None:
        self.split_list.clear()
        self._detected_format = None
        self.detected_format_label.setText(self._FORMAT_LABELS[None])
        QMessageBox.warning(self, "Fetch Splits Failed", error)

    def _validate_and_accept(self) -> bool:
        repo_id = self.repo_id_edit.text().strip()
        revision = self.revision_combo.currentText().strip()
        splits = self._checked_splits()
        output_dir = self.output_dir_edit.text().strip()

        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required.")
            return False
        if not revision:
            QMessageBox.warning(self, "Missing Required Field", "Branch is required.")
            return False
        if not splits:
            QMessageBox.warning(
                self, "Missing Required Field", "Select at least one split (fetch splits first if needed)."
            )
            return False
        if self._detected_format is None:
            QMessageBox.warning(self, "Format Unknown", "Fetch splits first so the dataset format can be detected.")
            return False
        if not output_dir:
            QMessageBox.warning(self, "Missing Required Field", "Output directory is required.")
            return False
        if self.dry_run_checkbox.isChecked() and self._detected_format == "parquet":
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
            "repo_id": self.repo_id_edit.text().strip(),
            "revision": self.revision_combo.currentText().strip() or "main",
            "splits": self._checked_splits(),
            "download_format": self._detected_format or "parquet",
            "output_dir": self.output_dir_edit.text().strip(),
            "dry_run": self.dry_run_checkbox.isChecked(),
            "token": self.token_edit.text().strip() or None,
        }

    def was_submitted(self) -> bool:
        return self._submitted

    def _load_settings(self) -> None:
        self._last_selected_splits: set[str] = set()
        if not self._settings:
            return
        repo_id = str(self._settings.value(self._KEY_REPO_ID, "") or "")
        revision = str(self._settings.value(self._KEY_REVISION, "main") or "main")
        splits_raw = str(self._settings.value(self._KEY_SPLITS, "") or "")
        self._last_selected_splits = {name for name in splits_raw.split("|") if name}

        if not repo_id or not self._last_selected_splits:
            default_transfer = self._AVAILABLE_DATASET_TRANSFERS[0]
            repo_id = repo_id or default_transfer["repo_id"]
            revision = revision if self._settings.contains(self._KEY_REVISION) else default_transfer["revision"]
            if not self._last_selected_splits:
                self._last_selected_splits = {default_transfer["split"]}

        self.repo_id_edit.setText(repo_id)
        self.revision_combo.setEditText(revision)
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
        self._settings.setValue(self._KEY_SPLITS, "|".join(payload["splits"]))
        self._settings.setValue(self._KEY_OUTPUT_DIR, self.output_dir_edit.text().strip())
        self._settings.setValue(self._KEY_DRY_RUN, self.dry_run_checkbox.isChecked())
        self._settings.setValue(self._KEY_TOKEN, self.token_edit.text().strip())
        self._settings.sync()


class HfOpenDownloadedSplitDialog(QDialog):
    """Lets the user pick one of several just-downloaded splits to open."""

    def __init__(self, entries: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Downloaded Dataset")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Multiple splits were downloaded. Choose one to open now:", self))

        self.entry_list = QListWidget(self)
        for label, json_path in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, json_path)
            self.entry_list.addItem(item)
        if self.entry_list.count():
            self.entry_list.setCurrentRow(0)
        layout.addWidget(self.entry_list)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        open_button = buttons.button(QDialogButtonBox.StandardButton.Open)
        if open_button:
            open_button.setText("Open")
        cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button:
            cancel_button.setText("Skip")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_json_path(self) -> str | None:
        item = self.entry_list.currentItem()
        if not item:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole) or "") or None


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

        self.repo_id_edit = QLineEdit(self)
        self.repo_id_edit.setPlaceholderText("OpenSportsLab/OSL-loc-tennis-public")
        form.addRow("Repo ID*", self.repo_id_edit)

        self.split_edit = QLineEdit(self)
        self.split_edit.setPlaceholderText("test")
        form.addRow("Split*", self.split_edit)

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
            self.split_edit,
            self.opened_json_edit,
            self.revision_edit,
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
        repo_id = self.repo_id_edit.text().strip()

        if not repo_id:
            QMessageBox.warning(self, "Missing Required Field", "Repo ID is required.")
            return
        if not self.split_edit.text().strip():
            QMessageBox.warning(self, "Missing Required Field", "Split is required.")
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
            "split": self.split_edit.text().strip(),
            "commit_message": self.commit_message_edit.text().strip() or "Upload dataset inputs from JSON",
            "token": self.token_edit.text().strip() or None,
            "upload_as_json": self.upload_as_json_checkbox.isChecked(),
            "shard_mode": "size",
            "shard_size": int(self.shard_size_spin.value()) * self._SHARD_SIZE_UNIT_BYTES,
        }

    def _load_settings(self) -> None:
        if self._settings:
            self.repo_id_edit.setText(str(self._settings.value(self._KEY_REPO_ID, "") or ""))
            self.revision_edit.setText(str(self._settings.value(self._KEY_REVISION, "main") or "main"))
            self.split_edit.setText(str(self._settings.value(self._KEY_SPLIT, "") or ""))
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
        if default_repo_id:
            self.repo_id_edit.setText(default_repo_id)
        if default_branch:
            self.revision_edit.setText(default_branch)
        if default_split:
            self.split_edit.setText(default_split)
        elif not self.split_edit.text().strip() and inferred_split:
            self.split_edit.setText(inferred_split)

    def _save_settings(self) -> None:
        if not self._settings:
            return
        self._settings.setValue(self._KEY_REPO_ID, self.repo_id_edit.text().strip())
        self._settings.setValue(self._KEY_REVISION, self.revision_edit.text().strip() or "main")
        self._settings.setValue(self._KEY_SPLIT, self.split_edit.text().strip())
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
