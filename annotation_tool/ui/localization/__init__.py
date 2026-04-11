import os

from PyQt6 import uic
from PyQt6.QtCore import QAbstractTableModel, QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from colors import (
    localization_label_color_hex,
    localization_label_hover_hex,
    localization_label_pressed_hex,
    localization_label_text_hex,
    normalize_hex_color,
)
from utils import resource_path


def _format_mmss_msec(ms: int) -> str:
    ms = max(0, int(ms))
    seconds = ms // 1000
    minutes = seconds // 60
    return f"{minutes:02}:{seconds % 60:02}.{ms % 1000:03}"


def _parse_time_to_ms(text: str, fallback: int = 0) -> int:
    value = (text or "").strip()
    if not value:
        return max(0, int(fallback))

    try:
        parts = value.split(":")
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            sec_parts = parts[2].split(".")
            seconds = int(sec_parts[0])
            millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
            return max(0, ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis)

        if len(parts) == 2:
            minutes = int(parts[0])
            sec_parts = parts[1].split(".")
            seconds = int(sec_parts[0])
            millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
            return max(0, (minutes * 60 + seconds) * 1000 + millis)

        if len(parts) == 1:
            return max(0, int(float(parts[0]) * 1000))
    except Exception:
        pass

    return max(0, int(fallback))


class _LocalizationTableModel(QAbstractTableModel):
    """
    Localization table model with editable Time/Head/Label columns.
    """

    itemChanged = pyqtSignal(dict, dict)

    def __init__(self, annotations=None):
        super().__init__()
        self._data = annotations or []
        self._headers = ["Time", "Head", "Label", "Confidence"]
        self._schema = {}

    def rowCount(self, parent=None):
        return len(self._data)

    def columnCount(self, parent=None):
        return len(self._headers)

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        if index.column() >= 3:
            return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        return (
            Qt.ItemFlag.ItemIsEnabled
            | Qt.ItemFlag.ItemIsSelectable
            | Qt.ItemFlag.ItemIsEditable
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()
        item = self._data[row]

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if col == 0:
                return _format_mmss_msec(item.get("position_ms", 0))
            if col == 1:
                return item.get("head", "").replace("_", " ")
            if col == 2:
                return item.get("label", "").replace("_", " ")
            if col == 3:
                if "confidence_score" not in item:
                    return ""
                try:
                    return f"{float(item.get('confidence_score') or 0.0) * 100.0:.1f}%"
                except Exception:
                    return ""

        if role == Qt.ItemDataRole.BackgroundRole:
            definition = self._schema.get(item.get("head", ""), {}) if isinstance(self._schema, dict) else {}
            label_colors = definition.get("label_colors", {}) if isinstance(definition, dict) else {}
            color = QColor(localization_label_color_hex(item.get("head", ""), item.get("label", ""), label_colors))
            color.setAlpha(72)
            return QBrush(color)

        if role == Qt.ItemDataRole.UserRole:
            return item

        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if not index.isValid() or role != Qt.ItemDataRole.EditRole:
            return False

        row = index.row()
        col = index.column()
        old_item = self._data[row]
        new_item = old_item.copy()
        value_str = str(value).strip()

        if col == 0:
            new_item["position_ms"] = _parse_time_to_ms(value_str, old_item.get("position_ms", 0))
        elif col == 1:
            new_item["head"] = value_str
        elif col == 2:
            new_item["label"] = value_str
        else:
            return False

        if new_item == old_item:
            return False

        self._data[row] = new_item
        self.itemChanged.emit(old_item, new_item)
        self.dataChanged.emit(
            index,
            index,
            [Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole, Qt.ItemDataRole.BackgroundRole],
        )
        return True

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def set_annotations(self, annotations):
        self.beginResetModel()
        self._data = annotations
        self.endResetModel()

    def set_schema(self, schema):
        self._schema = dict(schema or {})
        if self.rowCount() > 0:
            top_left = self.index(0, 0)
            bottom_right = self.index(self.rowCount() - 1, self.columnCount() - 1)
            self.dataChanged.emit(top_left, bottom_right, [Qt.ItemDataRole.BackgroundRole])

    def get_annotation_at(self, row):
        if 0 <= row < len(self._data):
            return self._data[row]
        return None


class _TableAdapter(QObject):
    """
    Adapter exposing the same table surface expected by controllers.
    Uses standard widgets defined in the panel .ui.
    """

    annotationSelected = pyqtSignal(int)
    annotationModified = pyqtSignal(dict, dict)
    annotationDeleted = pyqtSignal(dict)
    annotationConfirmRequested = pyqtSignal(dict)
    annotationRejectRequested = pyqtSignal(dict)
    updateTimeForSelectedRequested = pyqtSignal(dict)

    def __init__(
        self,
        table_view: QTableView,
        *,
        edit_label: QLabel | None = None,
        set_time_btn: QPushButton | None = None,
        list_label: QLabel | None = None,
        parent=None,
    ):
        super().__init__(parent)

        self.edit_lbl = edit_label
        self.btn_set_time = set_time_btn
        self.list_lbl = list_label
        self.table = table_view

        self.table.setProperty("class", "annotation_table")
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )

        self.model = _LocalizationTableModel()
        self.model.itemChanged.connect(self.annotationModified.emit)
        self.table.setModel(self.model)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        selection_model = self.table.selectionModel()
        if selection_model:
            selection_model.selectionChanged.connect(self._on_selection_changed)

        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.viewport().installEventFilter(self)

        if self.btn_set_time is not None:
            self.btn_set_time.setEnabled(False)
            self.btn_set_time.clicked.connect(self._on_set_time_clicked)

        self.current_schema = {}

    def eventFilter(self, watched, event):
        try:
            viewport = self.table.viewport()
        except RuntimeError:
            return False

        if watched is viewport and event.type() == QEvent.Type.MouseButtonDblClick:
            index = self.table.indexAt(event.position().toPoint())
            if index.isValid() and index.column() == 3:
                self._on_table_double_clicked(index)
                return True
        return super().eventFilter(watched, event)

    def set_data(self, annotations):
        self.model.set_annotations(annotations)

    def set_schema(self, schema):
        self.current_schema = schema
        self.model.set_schema(schema)

    def _on_selection_changed(self, selected, deselected):
        indexes = selected.indexes()
        has_selection = bool(indexes)

        if self.btn_set_time is not None:
            self.btn_set_time.setEnabled(has_selection)

        if not has_selection:
            return

        row = indexes[0].row()
        item = self.model.get_annotation_at(row)
        if item:
            self.annotationSelected.emit(item.get("position_ms", 0))

    def _on_set_time_clicked(self):
        if self.btn_set_time is None:
            return

        indexes = self.table.selectionModel().selectedRows()
        if not indexes:
            return

        row = indexes[0].row()
        item = self.model.get_annotation_at(row)
        if item:
            self.updateTimeForSelectedRequested.emit(item)

    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return

        row = index.row()
        item = self.model.get_annotation_at(row)
        if not item:
            return

        menu = QMenu(self.table)
        act_confirm = None
        act_reject = None
        if isinstance(item, dict) and "confidence_score" in item:
            act_confirm = menu.addAction("Confirm Annotation")
            act_reject = menu.addAction("Reject Annotation")
        act_delete = menu.addAction("Delete Event")
        selected_action = menu.exec(self.table.mapToGlobal(pos))

        if act_confirm is not None and selected_action == act_confirm:
            self.annotationConfirmRequested.emit(item)
            return
        if act_reject is not None and selected_action == act_reject:
            self.annotationRejectRequested.emit(item)
            return
        if selected_action == act_delete:
            self.annotationDeleted.emit(item)

    def _on_table_double_clicked(self, index):
        if not index.isValid():
            return
        if index.column() != 3:
            return
        item = self.model.get_annotation_at(index.row())
        if not isinstance(item, dict) or "confidence_score" not in item:
            return

        reply = QMessageBox.question(
            self.table,
            "Confirm Annotation",
            "Do you want to confirm that annotation?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.annotationConfirmRequested.emit(item)
        elif reply == QMessageBox.StandardButton.No:
            self.annotationRejectRequested.emit(item)


class _SpottingTabsAdapter(QObject):
    """
    Behavior adapter for head/label spotting tabs.
    Keeps the same signals/methods used by LocalizationEditorController.
    """

    headAdded = pyqtSignal(str)
    headRenamed = pyqtSignal(str, str)
    headDeleted = pyqtSignal(str)
    headSelected = pyqtSignal(str)
    spottingTriggered = pyqtSignal(str, str)
    labelAddReq = pyqtSignal(str)
    labelRenameReq = pyqtSignal(str, str)
    labelDeleteReq = pyqtSignal(str, str)
    labelColorReq = pyqtSignal(str, str, str)
    smartInferenceRequested = pyqtSignal(str)

    def __init__(self, tab_widget: QTabWidget, parent=None):
        super().__init__(parent)
        self._tabs = tab_widget
        self._tabs.setTabBarAutoHide(False)
        self._tabs.setMovable(False)
        self._tabs.setTabsClosable(False)
        self._tabs.setProperty("class", "spotting_tabs")

        self._tabs.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self._tabs.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tabs.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        self._ignore_change = False
        self._plus_tab_index = -1
        self._head_keys_map = []
        self._previous_index = -1
        self._head_pages = {}
        self._button_meta = {}

    def update_schema(self, label_definitions):
        self._ignore_change = True
        self._tabs.clear()
        self._head_keys_map = []
        self._head_pages.clear()
        self._button_meta.clear()

        heads = sorted(label_definitions.keys())
        for head in heads:
            definition = label_definitions[head]
            labels = definition.get("labels", [])
            page, time_label, scroll, smart_infer_btn = self._create_head_page()

            self._tabs.addTab(page, head.replace("_", " "))
            self._head_keys_map.append(head)
            self._head_pages[head] = {
                "time_label": time_label,
                "scroll": scroll,
                "labels": labels,
                "label_colors": dict(definition.get("label_colors", {})),
            }
            smart_infer_btn.clicked.connect(lambda _, h=head: self.smartInferenceRequested.emit(h))
            self._populate_head_buttons(head)

        self._plus_tab_index = self._tabs.addTab(QWidget(), "+")
        self._ignore_change = False

        if self._head_keys_map:
            self._tabs.setCurrentIndex(0)
            self._previous_index = 0
        else:
            self._previous_index = -1

    def update_current_time(self, time_str):
        current = self._tabs.currentIndex()
        if 0 <= current < len(self._head_keys_map):
            head = self._head_keys_map[current]
            label = self._head_pages[head]["time_label"]
            label.setText(f"Current Time: {time_str}")

    def set_current_head(self, head_name):
        if head_name in self._head_keys_map:
            idx = self._head_keys_map.index(head_name)
            self._tabs.setCurrentIndex(idx)
            self._previous_index = idx

    def _create_head_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(2, 2, 2, 2)
        page_layout.setSpacing(5)

        time_label = QLabel("Current Time: 00:00.000")
        time_label.setProperty("class", "spotting_time_lbl")
        time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout = QHBoxLayout()
        header_layout.addWidget(time_label)
        header_layout.addStretch()
        smart_infer_btn = QPushButton("Smart Inference")
        smart_infer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        header_layout.addWidget(smart_infer_btn)
        page_layout.addLayout(header_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setProperty("class", "spotting_scroll_area")
        page_layout.addWidget(scroll)

        return page, time_label, scroll, smart_infer_btn

    def _populate_head_buttons(self, head_name):
        page_info = self._head_pages.get(head_name)
        if page_info is None:
            return

        labels = page_info["labels"]
        label_colors = page_info.get("label_colors", {})
        scroll = page_info["scroll"]

        old_widget = scroll.takeWidget()
        if old_widget:
            old_widget.deleteLater()

        grid_container = QWidget()
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setSpacing(6)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        max_width = 360
        buttons_info = []

        for label in labels:
            display_text = label.replace("_", " ")
            btn = QPushButton(display_text)
            btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(28)
            btn.setProperty("class", "spotting_label_btn")
            btn.setStyleSheet(self._label_button_stylesheet(head_name, label, label_colors))

            btn.clicked.connect(lambda _, h=head_name, l=label: self.spottingTriggered.emit(h, l))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda _pos, b=btn, h=head_name, l=label: self._show_label_context_menu(b, h, l)
            )
            self._button_meta[btn] = (head_name, label)

            btn.adjustSize()
            buttons_info.append((btn, btn.sizeHint().width()))

        buttons_info.sort(key=lambda x: x[1], reverse=True)
        rows = []

        for btn, width in buttons_info:
            placed = False
            for row in rows:
                if row["width"] + width + 6 <= max_width:
                    row["layout"].addWidget(btn)
                    row["width"] += width + 6
                    placed = True
                    break

            if not placed:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(6)
                row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                grid_layout.addLayout(row_layout)
                row_layout.addWidget(btn)
                rows.append({"layout": row_layout, "width": width})

        add_btn = QPushButton("+ Add Label to Current Time")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setMinimumHeight(28)
        add_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        add_btn.setProperty("class", "spotting_add_btn")
        add_btn.clicked.connect(lambda _, h=head_name: self.labelAddReq.emit(h))
        add_btn.adjustSize()
        add_width = add_btn.sizeHint().width()

        placed = False
        for row in rows:
            if row["width"] + add_width + 6 <= max_width:
                row["layout"].addWidget(add_btn)
                row["width"] += add_width + 6
                placed = True
                break

        if not placed:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(6)
            row_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            grid_layout.addLayout(row_layout)
            row_layout.addWidget(add_btn)

        scroll.setWidget(grid_container)

    @staticmethod
    def _label_button_stylesheet(head_name: str, label: str, label_colors: dict | None = None) -> str:
        base = localization_label_color_hex(head_name, label, label_colors)
        hover = localization_label_hover_hex(base)
        pressed = localization_label_pressed_hex(base)
        text = localization_label_text_hex(base)
        return (
            "QPushButton {"
            f"background-color: {base};"
            f"color: {text};"
            f"border: 1px solid {pressed};"
            "border-radius: 6px;"
            "font-weight: bold;"
            "font-size: 13px;"
            "text-align: center;"
            "padding: 4px 10px;"
            "}"
            "QPushButton:hover {"
            f"background-color: {hover};"
            f"border-color: {hover};"
            "}"
            "QPushButton:pressed {"
            f"background-color: {pressed};"
            f"border-color: {pressed};"
            "}"
        )

    def _show_label_context_menu(self, button: QPushButton, head_name: str, label: str):
        display_label = label.replace("_", " ")
        menu = QMenu(button)
        rename_action = menu.addAction(f"Rename '{display_label}'")
        color_action = menu.addAction(f"Change Color for '{display_label}'")
        delete_action = menu.addAction(f"Delete '{display_label}'")

        action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if action == rename_action:
            self.labelRenameReq.emit(head_name, label)
        elif action == color_action:
            current_colors = self._head_pages.get(head_name, {}).get("label_colors", {})
            current_hex = localization_label_color_hex(head_name, label, current_colors)
            selected = QColorDialog.getColor(QColor(current_hex), button, f"Choose color for '{display_label}'")
            normalized = normalize_hex_color(selected.name()) if selected.isValid() else None
            if normalized:
                self.labelColorReq.emit(head_name, label, normalized)
        elif action == delete_action:
            self.labelDeleteReq.emit(head_name, label)

    def _on_tab_bar_clicked(self, index):
        if index != self._plus_tab_index or index == -1:
            return

        self._handle_add_head()
        if self._previous_index >= 0:
            self._tabs.setCurrentIndex(self._previous_index)

    def _on_tab_changed(self, index):
        if self._ignore_change:
            return

        if index == self._plus_tab_index or index == -1:
            return

        if 0 <= index < len(self._head_keys_map):
            head = self._head_keys_map[index]
            self.headSelected.emit(head)
            self._previous_index = index

    def _show_tab_context_menu(self, pos):
        index = self._tabs.tabBar().tabAt(pos)
        if index == -1 or index == self._plus_tab_index:
            return
        if not (0 <= index < len(self._head_keys_map)):
            return

        head_name = self._head_keys_map[index]
        display_name = self._tabs.tabText(index)

        menu = QMenu(self._tabs)
        rename_action = menu.addAction(f"Rename '{display_name}'")
        delete_action = menu.addAction(f"Delete '{display_name}'")

        action = menu.exec(self._tabs.tabBar().mapToGlobal(pos))
        if action == rename_action:
            new_name, ok = QInputDialog.getText(
                self._tabs,
                "Rename Head",
                f"Rename '{head_name}' to:",
                text=head_name,
            )
            if ok and new_name.strip() and new_name.strip() != head_name:
                self.headRenamed.emit(head_name, new_name.strip())
        elif action == delete_action:
            self.headDeleted.emit(head_name)

    def _handle_add_head(self):
        name, ok = QInputDialog.getText(
            self._tabs,
            "New Task Head",
            "Enter head name (e.g. 'player_action'):",
        )
        if ok and name.strip():
            self.headAdded.emit(name.strip())


class _AnnotationManagementAdapter(QObject):
    def __init__(self, spotting_tabs: QTabWidget, parent=None):
        super().__init__(parent)
        self.tabs = _SpottingTabsAdapter(spotting_tabs, parent)

    def update_schema(self, label_definitions):
        self.tabs.update_schema(label_definitions)


class _SmartWidgetAdapter(QObject):
    """
    Adapter that preserves the smart-widget API expected by controller code.
    Uses only standard widgets defined in localization_annotation_panel.ui.
    """

    setTimeRequested = pyqtSignal(str)
    runInferenceRequested = pyqtSignal(int, int)
    confirmSmartRequested = pyqtSignal()
    clearSmartRequested = pyqtSignal()

    def __init__(self, panel, parent=None):
        super().__init__(parent)

        self.val_start = panel.smartStartTimeEdit
        self.val_end = panel.smartEndTimeEdit
        self.btn_set_start = panel.smartSetStartBtn
        self.btn_set_end = panel.smartSetEndBtn
        self.btn_run_infer = panel.smartRunInferenceBtn
        self.btn_confirm = panel.smartConfirmBtn
        self.btn_clear = panel.smartClearBtn

        self.start_ms = 0
        self.end_ms = 0

        self.val_start.setText("00:00.000")
        self.val_end.setText("00:00.000")
        self.val_start.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.val_end.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Keep a compact monospaced look close to the previous custom line edit.
        line_edit_style = "font-family: monospace; font-weight: bold; font-size: 13px; padding: 2px;"
        self.val_start.setStyleSheet(line_edit_style)
        self.val_end.setStyleSheet(line_edit_style)

        self.btn_set_start.clicked.connect(lambda: self.setTimeRequested.emit("start"))
        self.btn_set_end.clicked.connect(lambda: self.setTimeRequested.emit("end"))
        self.btn_run_infer.clicked.connect(self._on_run_clicked)
        self.btn_confirm.clicked.connect(self.confirmSmartRequested.emit)
        self.btn_clear.clicked.connect(self.clearSmartRequested.emit)

        self.val_start.editingFinished.connect(self._on_start_edit_finished)
        self.val_end.editingFinished.connect(self._on_end_edit_finished)

        self.smart_table = _TableAdapter(
            panel.smartEventsTableView,
            edit_label=None,
            set_time_btn=None,
            list_label=panel.smartEventsListLabel,
            parent=self,
        )

    def update_time_display(self, target: str, time_str: str, time_ms: int):
        if target == "start":
            self.start_ms = max(0, int(time_ms))
            self.val_start.setText(_format_mmss_msec(self.start_ms))
            if self.end_ms > 0 and self.start_ms > self.end_ms:
                self.end_ms = self.start_ms
                self.val_end.setText(_format_mmss_msec(self.end_ms))
            return

        if target == "end":
            self.end_ms = max(0, int(time_ms))
            self.val_end.setText(_format_mmss_msec(self.end_ms))
            if self.end_ms > 0 and self.end_ms < self.start_ms:
                self.start_ms = self.end_ms
                self.val_start.setText(_format_mmss_msec(self.start_ms))

    def _on_start_edit_finished(self):
        self.start_ms = _parse_time_to_ms(self.val_start.text(), self.start_ms)
        self.val_start.setText(_format_mmss_msec(self.start_ms))

        if self.end_ms > 0 and self.start_ms > self.end_ms:
            self.end_ms = self.start_ms
            self.val_end.setText(_format_mmss_msec(self.end_ms))

    def _on_end_edit_finished(self):
        self.end_ms = _parse_time_to_ms(self.val_end.text(), self.end_ms)
        self.val_end.setText(_format_mmss_msec(self.end_ms))

        if self.end_ms > 0 and self.end_ms < self.start_ms:
            self.start_ms = self.end_ms
            self.val_start.setText(_format_mmss_msec(self.start_ms))

    def _on_run_clicked(self):
        self.runInferenceRequested.emit(self.start_ms, self.end_ms)


class LocalizationAnnotationPanel(QWidget):
    """
    Localization right-panel view loaded from Qt Designer UI.
    The .ui defines only standard Qt widgets; behavior is attached via adapters.
    """

    tabSwitched = pyqtSignal(int)
    eventNavigateRequested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "localization", "localization_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load LocalizationAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        # Preserve controller-facing API.
        self.tabs = self.localizationTabs
        self.annot_mgmt = _AnnotationManagementAdapter(self.spottingTabs, self)
        self.table = _TableAdapter(
            self.handEventsTableView,
            edit_label=self.handEditLabel,
            set_time_btn=self.handSetCurrentTimeBtn,
            list_label=self.handEventsListLabel,
            parent=self,
        )
        for idx in reversed(range(self.tabs.count())):
            if self.tabs.widget(idx) is getattr(self, "smartAnnotationTab", None):
                self.tabs.removeTab(idx)
                break

        if self.tabs.count() <= 1:
            self.tabs.tabBar().hide()

        self.tabs.currentChanged.connect(self.tabSwitched.emit)
        self.btn_prev_event.clicked.connect(lambda: self.eventNavigateRequested.emit(-1))
        self.btn_next_event.clicked.connect(lambda: self.eventNavigateRequested.emit(1))


__all__ = ["LocalizationAnnotationPanel"]
