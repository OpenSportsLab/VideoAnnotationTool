import os
from urllib.parse import urlparse
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QRadioButton, QTreeView, QDialogButtonBox,
    QAbstractItemView, QGroupBox, QFormLayout, QLineEdit, QHBoxLayout,
    QFrame, QListWidget, QComboBox, QPushButton, QLabel, QProgressBar,
    QMessageBox, QWidget, QListWidgetItem, QStyle, QButtonGroup, QScrollArea,
    QFileDialog, QCheckBox, QSizePolicy, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QPlainTextEdit
)
from PyQt6.QtCore import QDir, Qt, QSize, QSettings, pyqtSignal
from PyQt6.QtGui import QFileSystemModel, QIcon
from utils import get_square_remove_btn_style
from media_control_settings import (
    DEFAULT_PLAYBACK_FACTORS,
    DEFAULT_SEEK_INTERVALS,
    parse_playback_factors,
    parse_seek_intervals,
)
from inference_settings import (
    BACKEND_KEY,
    DEFAULT_BACKEND,
    DEFAULT_SERVER_URL,
    LOCAL_MODELS_KEY,
    SERVER_URL_KEY,
    load_local_models,
    load_shared_mappings,
    normalize_server_url,
)
from inference_types import INFERENCE_TASKS


class InferenceConfigurationWidget(QWidget):
    """Reusable editor for local/remote provider configuration."""

    testConnectionRequested = pyqtSignal(object)
    configurationChanged = pyqtSignal()

    def __init__(self, config=None, *, collapsible=False, parent=None):
        super().__init__(parent)
        config = dict(config or {})
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        root.addLayout(form)
        self.backend_combo = QComboBox(self)
        self.backend_combo.addItem("Local (OpenSportsLib)", "local")
        self.backend_combo.addItem("Remote server", "remote")
        self.backend_combo.setCurrentIndex(1 if config.get("backend") == "remote" else 0)
        form.addRow("Backend:", self.backend_combo)

        self.advanced_group = QGroupBox("Advanced connection and model settings", self)
        self.advanced_group.setCheckable(bool(collapsible))
        self.advanced_group.setChecked(not collapsible)
        advanced = QVBoxLayout(self.advanced_group)
        remote_form = QFormLayout()
        advanced.addLayout(remote_form)
        server_row = QWidget(self.advanced_group)
        server_layout = QHBoxLayout(server_row)
        server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_url_edit = QLineEdit(str(config.get("server_url") or DEFAULT_SERVER_URL), server_row)
        self.test_button = QPushButton("Test Connection", server_row)
        server_layout.addWidget(self.server_url_edit, 1)
        server_layout.addWidget(self.test_button)
        remote_form.addRow("Server URL:", server_row)
        self.connection_status = QLabel("", self.advanced_group)
        self.connection_status.setWordWrap(True)
        advanced.addWidget(self.connection_status)

        advanced.addWidget(QLabel("Shared storage mappings", self.advanced_group))
        self.mapping_table = QTableWidget(0, 2, self.advanced_group)
        self.mapping_table.setHorizontalHeaderLabels(["Local directory", "Server root ID"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        advanced.addWidget(self.mapping_table)
        mapping_buttons = QHBoxLayout()
        self.add_mapping_button = QPushButton("Add Mapping", self.advanced_group)
        self.remove_mapping_button = QPushButton("Remove Mapping", self.advanced_group)
        mapping_buttons.addWidget(self.add_mapping_button)
        mapping_buttons.addWidget(self.remove_mapping_button)
        mapping_buttons.addStretch(1)
        advanced.addLayout(mapping_buttons)

        advanced.addWidget(QLabel("Local model registry", self.advanced_group))
        self.local_model_table = QTableWidget(0, 5, self.advanced_group)
        self.local_model_table.setHorizontalHeaderLabels(["Task", "Model ID", "Display name", "Config YAML", "Weights"])
        self.local_model_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        advanced.addWidget(self.local_model_table)
        model_buttons = QHBoxLayout()
        self.add_local_model_button = QPushButton("Add Local Model", self.advanced_group)
        self.remove_local_model_button = QPushButton("Remove Local Model", self.advanced_group)
        model_buttons.addWidget(self.add_local_model_button)
        model_buttons.addWidget(self.remove_local_model_button)
        model_buttons.addStretch(1)
        advanced.addLayout(model_buttons)
        root.addWidget(self.advanced_group)

        for mapping in config.get("shared_mappings", []):
            self.append_mapping(mapping.get("local_root", ""), mapping.get("root_id", ""))
        for model in config.get("local_models", []):
            self.append_local_model(model)
        self.add_mapping_button.clicked.connect(lambda: self.append_mapping("", ""))
        self.remove_mapping_button.clicked.connect(lambda: self._remove_row(self.mapping_table))
        self.add_local_model_button.clicked.connect(lambda: self.append_local_model({"task": "classification"}))
        self.remove_local_model_button.clicked.connect(lambda: self._remove_row(self.local_model_table))
        self.test_button.clicked.connect(lambda: self.testConnectionRequested.emit(self.payload()))
        self.backend_combo.currentIndexChanged.connect(self._changed)
        self.server_url_edit.textChanged.connect(self._changed)
        self._changed()

    def _changed(self, *_args):
        self.connection_status.clear()
        parsed = urlparse(self.server_url_edit.text().strip())
        if (
            self.backend_combo.currentData() == "remote"
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
        for column, value in enumerate((model.get("task", "classification"), model.get("id", ""), model.get("display_name", ""), model.get("config_path", ""), model.get("weights", ""))):
            self.local_model_table.setItem(row, column, QTableWidgetItem(str(value or "")))

    def set_connection_status(self, text, success):
        self.connection_status.setText(str(text or ""))
        self.connection_status.setStyleSheet("color: #27823b;" if success else "color: #d9534f;")

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
            models.append({"task": task, "id": model_id, "display_name": display_name or model_id, "config_path": config_path, "weights": weights, "available": True, "accepted_input_types": ["video"]})
        return {"backend": str(self.backend_combo.currentData()), "server_url": normalize_server_url(self.server_url_edit.text()), "shared_mappings": mappings, "local_models": models}


class ApplicationSettingsDialog(QDialog):
    """Extensible application settings dialog, initially for media controls."""

    mediaControlsApplyRequested = pyqtSignal(str, str, object, object)
    inferenceSettingsApplyRequested = pyqtSignal(object)
    inferenceTestRequested = pyqtSignal()

    def __init__(
        self,
        playback_factors: str,
        seek_intervals: str,
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

        self._settings = settings
        inference_page = QWidget(tabs)
        inference_layout = QVBoxLayout(inference_page)
        inference_config = {
            "backend": str(settings.value(BACKEND_KEY, DEFAULT_BACKEND) if settings is not None else DEFAULT_BACKEND),
            "server_url": str(settings.value(SERVER_URL_KEY, DEFAULT_SERVER_URL) if settings is not None else DEFAULT_SERVER_URL),
            "shared_mappings": load_shared_mappings(settings),
            "local_models": load_local_models(settings),
        }
        self.inference_configuration_widget = InferenceConfigurationWidget(inference_config, parent=inference_page)
        inference_layout.addWidget(self.inference_configuration_widget)
        self.inference_backend_combo = self.inference_configuration_widget.backend_combo
        self.inference_server_url_edit = self.inference_configuration_widget.server_url_edit
        self.inference_test_button = self.inference_configuration_widget.test_button
        self.inference_connection_status = self.inference_configuration_widget.connection_status
        self.shared_mapping_table = self.inference_configuration_widget.mapping_table
        self.local_model_table = self.inference_configuration_widget.local_model_table
        self.add_mapping_button = self.inference_configuration_widget.add_mapping_button
        self.remove_mapping_button = self.inference_configuration_widget.remove_mapping_button
        self.add_local_model_button = self.inference_configuration_widget.add_local_model_button
        self.remove_local_model_button = self.inference_configuration_widget.remove_local_model_button

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
        self.inference_configuration_widget.testConnectionRequested.connect(lambda _config: self.inferenceTestRequested.emit())

    def _append_mapping(self, local_root: str, root_id: str):
        self.inference_configuration_widget.append_mapping(local_root, root_id)

    def _remove_selected_mapping(self):
        row = self.shared_mapping_table.currentRow()
        if row >= 0:
            self.shared_mapping_table.removeRow(row)

    def _append_local_model(self, model: dict):
        self.inference_configuration_widget.append_local_model(model)

    def _remove_selected_local_model(self):
        row = self.local_model_table.currentRow()
        if row >= 0:
            self.local_model_table.removeRow(row)

    def set_inference_connection_status(self, text: str, success: bool):
        self.inference_configuration_widget.set_connection_status(text, success)

    def inference_payload(self) -> dict:
        return self.inference_configuration_widget.payload()

    def _restore_defaults(self) -> None:
        self.playback_factors_edit.setText(DEFAULT_PLAYBACK_FACTORS)
        self.seek_intervals_edit.setText(DEFAULT_SEEK_INTERVALS)
        self.validation_label.clear()

    def _apply(self, *, close_after: bool) -> None:
        try:
            factors = parse_playback_factors(self.playback_factors_edit.text())
            intervals = parse_seek_intervals(self.seek_intervals_edit.text())
            inference_payload = self.inference_payload()
        except ValueError as exc:
            self.validation_label.setText(str(exc))
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
        self.inferenceSettingsApplyRequested.emit(inference_payload)
        parsed_server = urlparse(inference_payload["server_url"])
        if (
            inference_payload["backend"] == "remote"
            and parsed_server.scheme == "http"
            and parsed_server.hostname not in {"127.0.0.1", "localhost", "::1"}
        ):
            self.set_inference_connection_status(
                "Warning: this server is unauthenticated and unencrypted. Use it only on a trusted network.",
                False,
            )
        if close_after:
            self.accept()


class InferenceRunDialog(QDialog):
    """Reusable task-aware model and input selection dialog."""

    refreshModelsRequested = pyqtSignal(str, str)
    testConnectionRequested = pyqtSignal(object)

    def __init__(self, task: str, inputs: list, context: dict | None = None, *, default_backend="local", provider_config=None, parent=None):
        super().__init__(parent)
        self.task = str(task)
        self.inputs = list(inputs or [])
        self.context = dict(context or {})
        self.setWindowTitle("Run Inference")
        self.resize(720, 620)
        layout = QVBoxLayout(self)
        config = dict(provider_config or {})
        config["backend"] = default_backend
        self.configuration_widget = InferenceConfigurationWidget(config, collapsible=True, parent=self)
        layout.addWidget(self.configuration_widget)
        form = QFormLayout()
        layout.addLayout(form)
        self.backend_combo = self.configuration_widget.backend_combo

        model_row = QWidget(self)
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        self.model_combo = QComboBox(model_row)
        self.refresh_models_button = QPushButton("Refresh", model_row)
        model_layout.addWidget(self.model_combo, 1)
        model_layout.addWidget(self.refresh_models_button)
        form.addRow("Model:", model_row)

        self.head_edit = QLineEdit(str(self.context.get("head") or ""), self)
        self.head_edit.setVisible(self.task in {"classification", "localization"})
        if self.task in {"classification", "localization"}:
            form.addRow("Head:", self.head_edit)

        self.start_spin = QSpinBox(self)
        self.start_spin.setRange(0, 2_147_483_647)
        self.start_spin.setValue(int(self.context.get("start_ms", 0) or 0))
        self.end_spin = QSpinBox(self)
        self.end_spin.setRange(0, 2_147_483_647)
        self.end_spin.setValue(int(self.context.get("end_ms", 0) or 0))
        if self.task in {"localization", "dense_description"}:
            form.addRow("Start (ms):", self.start_spin)
            form.addRow("End (ms, 0 = end):", self.end_spin)

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
        self.remember_defaults_checkbox = QCheckBox("Remember these settings as defaults", self)
        layout.addWidget(self.remember_defaults_checkbox)
        self.run_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self.run_buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Run")
        layout.addWidget(self.run_buttons)

        self.run_buttons.accepted.connect(self._accept_if_valid)
        self.run_buttons.rejected.connect(self.reject)
        self.refresh_models_button.clicked.connect(self._request_refresh)
        self.backend_combo.currentIndexChanged.connect(lambda _index: self._request_refresh())
        self.configuration_widget.testConnectionRequested.connect(self.testConnectionRequested.emit)
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
        self.refreshModelsRequested.emit(str(self.backend_combo.currentData()), self.task)

    def set_models(self, models):
        previous = str(self.model_combo.currentData() or "")
        self.model_combo.clear()
        for descriptor in list(models or []):
            suffix = "" if descriptor.available else " (unavailable)"
            self.model_combo.addItem(f"{descriptor.display_name}{suffix}", descriptor.id)
            self.model_combo.setItemData(
                self.model_combo.count() - 1,
                descriptor,
                Qt.ItemDataRole.UserRole + 1,
            )
        if previous:
            index = self.model_combo.findData(previous)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self._update_model_availability()

    def _update_model_availability(self):
        descriptor = self.model_combo.currentData(Qt.ItemDataRole.UserRole + 1)
        available = bool(descriptor is not None and descriptor.available)
        message = "" if descriptor is None else descriptor.unavailable_reason
        if descriptor is None:
            message = "No compatible models were discovered."
        self.availability_label.setText(message)
        self.run_buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(available)
        accepted_types = set(descriptor.accepted_input_types) if descriptor is not None else set()
        for index in range(self.input_list.count()):
            item = self.input_list.item(index)
            source = item.data(Qt.ItemDataRole.UserRole)
            compatible = not accepted_types or getattr(source, "type", "video") in accepted_types
            flags = item.flags()
            if compatible:
                item.setFlags(flags | Qt.ItemFlag.ItemIsEnabled)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
                item.setFlags(flags & ~Qt.ItemFlag.ItemIsEnabled)
        supports_range = bool(descriptor is not None and descriptor.supports_time_range)
        self.start_spin.setEnabled(supports_range)
        self.end_spin.setEnabled(supports_range)

    def _accept_if_valid(self):
        selected_inputs = self.selected_inputs()
        if not selected_inputs:
            self.availability_label.setText("Select at least one input.")
            return
        descriptor = self.model_combo.currentData(Qt.ItemDataRole.UserRole + 1)
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
        if self.end_spin.value() and self.end_spin.value() <= self.start_spin.value():
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
        config = self.configuration_widget.payload()
        return {
            "backend": str(self.backend_combo.currentData()),
            "model_id": str(self.model_combo.currentData() or ""),
            "inputs": self.selected_inputs(),
            "head": self.head_edit.text().strip(),
            "start_ms": self.start_spin.value(),
            "end_ms": self.end_spin.value(),
            "language": self.language_edit.text().strip() or "en",
            "question": self.question_edit.toPlainText().strip(),
            "provider_config": config,
            "remember_defaults": self.remember_defaults_checkbox.isChecked(),
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
    _KEY_SPLIT = f"{_SETTINGS_PREFIX}/split"
    _KEY_DOWNLOAD_FORMAT = f"{_SETTINGS_PREFIX}/download_format"
    _KEY_SUCCESS_TRANSFERS = f"{_SETTINGS_PREFIX}/successful_transfers"
    _KEY_SUCCESS_URLS = f"{_SETTINGS_PREFIX}/successful_urls"
    _KEY_OUTPUT_DIR = f"{_SETTINGS_PREFIX}/output_dir"
    _KEY_DRY_RUN = f"{_SETTINGS_PREFIX}/dry_run"
    _KEY_TOKEN = f"{_SETTINGS_PREFIX}/token"
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

        self.repo_id_edit = QLineEdit(self)
        self.repo_id_edit.setPlaceholderText("OpenSportsLab/OSL-XFoul")
        form.addRow("Repo ID*", self.repo_id_edit)

        self.revision_edit = QLineEdit("main", self)
        self.revision_edit.setPlaceholderText("main-parquet")
        form.addRow("Branch*", self.revision_edit)

        self.split_edit = QLineEdit(self)
        self.split_edit.setPlaceholderText("test")
        form.addRow("Split*", self.split_edit)

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
        for edit in (self.repo_id_edit, self.revision_edit, self.split_edit, self.output_dir_edit, self.token_edit):
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
        repo_id = self.repo_id_edit.text().strip()
        revision = self.revision_edit.text().strip()
        split = self.split_edit.text().strip()
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
            "repo_id": self.repo_id_edit.text().strip(),
            "revision": self.revision_edit.text().strip() or "main",
            "split": self.split_edit.text().strip(),
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
        self.repo_id_edit.setText(normalized["repo_id"])
        self.revision_edit.setText(normalized["revision"])
        self.split_edit.setText(normalized["split"])
        index = self.download_format_combo.findData(normalized["download_format"])
        self.download_format_combo.setCurrentIndex(index if index >= 0 else 0)


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
