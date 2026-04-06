import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.common.annotation_table import AnnotationTableModel, AnnotationTableWidget
from utils import resource_path


class LabelButton(QPushButton):
    """
    Custom label button that supports right-click and double-click actions.
    """

    rightClicked = pyqtSignal()
    doubleClicked = pyqtSignal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(28)
        self.setStyleSheet("padding: 2px 10px;")
        self.setProperty("class", "spotting_label_btn")

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()
            return
        super().mouseDoubleClickEvent(event)


class HeadSpottingPage(QWidget):
    """
    One head/category page containing all label buttons.
    """

    labelClicked = pyqtSignal(str)
    addLabelRequested = pyqtSignal()
    renameLabelRequested = pyqtSignal(str)
    deleteLabelRequested = pyqtSignal(str)

    def __init__(self, head_name, labels, parent=None):
        super().__init__(parent)
        self.head_name = head_name
        self.labels = labels

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(5)

        self.time_label = QLabel("Current Time: 00:00.000")
        self.time_label.setProperty("class", "spotting_time_lbl")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.time_label)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setProperty("class", "spotting_scroll_area")
        layout.addWidget(self.scroll)

        self._populate_grid()

    def update_time_display(self, text: str):
        self.time_label.setText(f"Current Time: {text}")

    def refresh_labels(self, new_labels):
        self.labels = new_labels
        self._populate_grid()

    def _populate_grid(self):
        old_widget = self.scroll.takeWidget()
        if old_widget:
            old_widget.deleteLater()

        self.grid_container = QWidget()
        self.grid_layout = QVBoxLayout(self.grid_container)
        self.grid_layout.setSpacing(6)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        max_width = 360
        buttons_info = []
        for lbl in self.labels:
            display_text = lbl.replace("_", " ")
            btn = LabelButton(display_text)
            btn.clicked.connect(lambda _, l=lbl: self.labelClicked.emit(l))
            btn.rightClicked.connect(lambda l=lbl: self._show_context_menu(l))
            btn.doubleClicked.connect(lambda l=lbl: self.renameLabelRequested.emit(l))

            btn.adjustSize()
            btn_width = btn.sizeHint().width()
            buttons_info.append((btn, btn_width))

        buttons_info.sort(key=lambda x: x[1], reverse=True)
        rows = []

        for btn, btn_width in buttons_info:
            placed = False
            for row in rows:
                if row["width"] + btn_width + 6 <= max_width:
                    row["layout"].addWidget(btn)
                    row["width"] += btn_width + 6
                    placed = True
                    break

            if not placed:
                new_layout = QHBoxLayout()
                new_layout.setSpacing(6)
                new_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
                self.grid_layout.addLayout(new_layout)
                new_layout.addWidget(btn)
                rows.append({"layout": new_layout, "width": btn_width})

        add_btn = QPushButton("+ Add Label to Current Time")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setMinimumHeight(28)
        add_btn.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
        add_btn.setProperty("class", "spotting_add_btn")
        add_btn.clicked.connect(self.addLabelRequested.emit)
        add_btn.adjustSize()
        add_btn_width = add_btn.sizeHint().width()

        placed_add = False
        for row in rows:
            if row["width"] + add_btn_width + 6 <= max_width:
                row["layout"].addWidget(add_btn)
                row["width"] += add_btn_width + 6
                placed_add = True
                break

        if not placed_add:
            new_layout = QHBoxLayout()
            new_layout.setSpacing(6)
            new_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self.grid_layout.addLayout(new_layout)
            new_layout.addWidget(add_btn)

        self.scroll.setWidget(self.grid_container)

    def _show_context_menu(self, label):
        display_label = label.replace("_", " ")
        menu = QMenu(self)
        rename_action = menu.addAction(f"Rename '{display_label}'")
        delete_action = menu.addAction(f"Delete '{display_label}'")

        action = menu.exec(self.cursor().pos())
        if action == rename_action:
            self.renameLabelRequested.emit(label)
        elif action == delete_action:
            self.deleteLabelRequested.emit(label)


class SpottingTabWidget(QTabWidget):
    """
    QTabWidget containing one tab per head/category plus a trailing "+" tab.
    """

    headAdded = pyqtSignal(str)
    headRenamed = pyqtSignal(str, str)
    headDeleted = pyqtSignal(str)
    headSelected = pyqtSignal(str)
    spottingTriggered = pyqtSignal(str, str)
    labelAddReq = pyqtSignal(str)
    labelRenameReq = pyqtSignal(str, str)
    labelDeleteReq = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBarAutoHide(False)
        self.setMovable(False)
        self.setTabsClosable(False)
        self.setProperty("class", "spotting_tabs")

        self.tabBar().tabBarClicked.connect(self._on_tab_bar_clicked)
        self.currentChanged.connect(self._on_tab_changed)

        self.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tabBar().customContextMenuRequested.connect(self._show_tab_context_menu)

        self._ignore_change = False
        self._plus_tab_index = -1
        self._head_keys_map = []
        self._previous_index = -1

    def update_schema(self, label_definitions):
        self._ignore_change = True
        self.clear()
        self._head_keys_map = []

        heads = sorted(label_definitions.keys())
        for head in heads:
            labels = label_definitions[head].get("labels", [])
            page = HeadSpottingPage(head, labels)

            page.labelClicked.connect(lambda l, h=head: self.spottingTriggered.emit(h, l))
            page.addLabelRequested.connect(lambda h=head: self.labelAddReq.emit(h))
            page.renameLabelRequested.connect(lambda l, h=head: self.labelRenameReq.emit(h, l))
            page.deleteLabelRequested.connect(lambda l, h=head: self.labelDeleteReq.emit(h, l))

            self.addTab(page, head.replace("_", " "))
            self._head_keys_map.append(head)

        self._plus_tab_index = self.addTab(QWidget(), "+")
        self._ignore_change = False

    def update_current_time(self, time_str):
        current_widget = self.currentWidget()
        if isinstance(current_widget, HeadSpottingPage):
            current_widget.update_time_display(time_str)

    def set_current_head(self, head_name):
        if head_name in self._head_keys_map:
            idx = self._head_keys_map.index(head_name)
            self.setCurrentIndex(idx)
            self._previous_index = idx

    def _on_tab_bar_clicked(self, index):
        if index == self._plus_tab_index and index != -1:
            self._handle_add_head()

    def _on_tab_changed(self, index):
        if self._ignore_change:
            return
        if index != self._plus_tab_index and index != -1:
            if 0 <= index < len(self._head_keys_map):
                real_head = self._head_keys_map[index]
                self.headSelected.emit(real_head)
                self._previous_index = index

    def _handle_add_head(self):
        name, ok = QInputDialog.getText(
            self,
            "New Task Head",
            "Enter head name (e.g. 'player_action'):",
        )
        if ok and name.strip():
            self.headAdded.emit(name.strip())

    def _show_tab_context_menu(self, pos):
        index = self.tabBar().tabAt(pos)
        if index == -1 or index == self._plus_tab_index:
            return
        if not (0 <= index < len(self._head_keys_map)):
            return

        real_head_name = self._head_keys_map[index]
        display_head_name = self.tabText(index)

        menu = QMenu(self)
        rename_act = menu.addAction(f"Rename '{display_head_name}'")
        delete_act = menu.addAction(f"Delete '{display_head_name}'")

        action = menu.exec(self.tabBar().mapToGlobal(pos))
        if action == rename_act:
            new_name, ok = QInputDialog.getText(
                self,
                "Rename Head",
                f"Rename '{real_head_name}' to:",
                text=real_head_name,
            )
            if ok and new_name.strip() and new_name != real_head_name:
                self.headRenamed.emit(real_head_name, new_name.strip())
        elif action == delete_act:
            self.headDeleted.emit(real_head_name)


class AnnotationManagementWidget(QWidget):
    """
    Wrapper for spotting tabs with the "Create Annotation" section title.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        title_label = QLabel("Create Annotation")
        title_label.setProperty("class", "panel_header_lbl")
        layout.addWidget(title_label)

        self.tabs = SpottingTabWidget()
        layout.addWidget(self.tabs)

    def update_schema(self, label_definitions):
        self.tabs.update_schema(label_definitions)


class TimeLineEdit(QLineEdit):
    """
    Editable MM:SS.mmm time field with up/down step control.
    """

    timeChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ms = 0
        self.setText("00:00.000")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-family: monospace; font-weight: bold; font-size: 13px; padding: 2px;")
        self.setFixedWidth(100)
        self.editingFinished.connect(self._on_edit_finished)

    def set_time_ms(self, ms: int):
        self._ms = max(0, ms)
        self.setText(self._fmt_ms(self._ms))
        self.timeChanged.emit(self._ms)

    def get_time_ms(self) -> int:
        return self._ms

    def _fmt_ms(self, ms: int) -> str:
        seconds = ms // 1000
        minutes = seconds // 60
        return f"{minutes:02}:{seconds % 60:02}.{ms % 1000:03}"

    def _parse_time(self, text: str) -> int:
        try:
            parts = text.split(":")
            if len(parts) >= 2:
                minutes = int(parts[0])
                second_parts = parts[1].split(".")
                seconds = int(second_parts[0])
                milli = int(second_parts[1]) if len(second_parts) > 1 else 0
                return (minutes * 60 + seconds) * 1000 + milli
        except Exception:
            pass
        return self._ms

    def _on_edit_finished(self):
        parsed_ms = self._parse_time(self.text())
        self.set_time_ms(parsed_ms)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Up:
            self._adjust_time(1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Down:
            self._adjust_time(-1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _adjust_time(self, direction: int):
        cursor = self.cursorPosition()
        ms = self._ms

        if cursor <= 2:
            ms += direction * 60000
        elif cursor <= 5:
            ms += direction * 1000
        else:
            ms += direction * 100

        self.set_time_ms(max(0, ms))
        self.setCursorPosition(cursor)


class SmartSpottingWidget(QWidget):
    """
    Smart localization inference controls and prediction table.
    """

    setTimeRequested = pyqtSignal(str)
    runInferenceRequested = pyqtSignal(int, int)
    confirmSmartRequested = pyqtSignal()
    clearSmartRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.start_ms = 0
        self.end_ms = 0

        self.time_box = QGroupBox("Smart Inference Range")
        self.time_box.setProperty("class", "smart_inference_box")
        time_layout = QVBoxLayout(self.time_box)

        start_row = QHBoxLayout()
        self.lbl_start = QLabel("Start Time:")
        self.val_start = TimeLineEdit()
        self.btn_set_start = QPushButton("Set to Current")
        self.btn_set_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_set_start.clicked.connect(lambda: self.setTimeRequested.emit("start"))
        self.val_start.timeChanged.connect(self._on_start_changed)
        start_row.addWidget(self.lbl_start)
        start_row.addWidget(self.val_start)
        start_row.addStretch()
        start_row.addWidget(self.btn_set_start)

        end_row = QHBoxLayout()
        self.lbl_end = QLabel("End Time:")
        self.val_end = TimeLineEdit()
        self.btn_set_end = QPushButton("Set to Current")
        self.btn_set_end.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_set_end.clicked.connect(lambda: self.setTimeRequested.emit("end"))
        self.val_end.timeChanged.connect(self._on_end_changed)
        end_row.addWidget(self.lbl_end)
        end_row.addWidget(self.val_end)
        end_row.addStretch()
        end_row.addWidget(self.btn_set_end)

        time_layout.addLayout(start_row)
        time_layout.addLayout(end_row)

        self.btn_run_infer = QPushButton("Run Smart Inference")
        self.btn_run_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_infer.setProperty("class", "run_inference_btn")
        self.btn_run_infer.clicked.connect(self._on_run_clicked)
        time_layout.addWidget(self.btn_run_infer)
        layout.addWidget(self.time_box, 0)

        self.smart_table = AnnotationTableWidget()
        self.smart_table.edit_lbl.hide()
        self.smart_table.btn_set_time.hide()
        self.smart_table.list_lbl.setText("Predicted Events List")
        layout.addWidget(self.smart_table, 1)

        bottom_row = QHBoxLayout()
        self.btn_confirm = QPushButton("Confirm Predictions")
        self.btn_confirm.setProperty("class", "editor_save_btn")
        self.btn_confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_confirm.clicked.connect(self.confirmSmartRequested.emit)

        self.btn_clear = QPushButton("Clear Predictions")
        self.btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clearSmartRequested.emit)

        bottom_row.addWidget(self.btn_confirm)
        bottom_row.addWidget(self.btn_clear)
        layout.addLayout(bottom_row)

    def _on_start_changed(self, ms: int):
        self.start_ms = ms
        if self.end_ms > 0 and self.start_ms > self.end_ms:
            self.val_end.blockSignals(True)
            self.val_end.set_time_ms(self.start_ms)
            self.end_ms = self.start_ms
            self.val_end.blockSignals(False)

    def _on_end_changed(self, ms: int):
        self.end_ms = ms
        if self.end_ms > 0 and self.end_ms < self.start_ms:
            self.val_start.blockSignals(True)
            self.val_start.set_time_ms(self.end_ms)
            self.start_ms = self.end_ms
            self.val_start.blockSignals(False)

    def update_time_display(self, target: str, time_str: str, time_ms: int):
        if target == "start":
            self.val_start.set_time_ms(time_ms)
        elif target == "end":
            self.val_end.set_time_ms(time_ms)

    def _on_run_clicked(self):
        self.runInferenceRequested.emit(self.start_ms, self.end_ms)


class LocalizationAnnotationPanel(QWidget):
    """
    Localization right-panel view loaded from Qt Designer UI.
    Exposes the same panel surface used by localization controllers/tests.
    """

    tabSwitched = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "localization", "annotation_panel", "localization_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load LocalizationAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.tabs = self.localizationTabs

        self.annot_mgmt = AnnotationManagementWidget(self.handAnnotationMgmtContainer)
        annot_layout = self.handAnnotationMgmtContainer.layout()
        if annot_layout is None:
            annot_layout = QVBoxLayout(self.handAnnotationMgmtContainer)
            annot_layout.setContentsMargins(0, 0, 0, 0)
        annot_layout.addWidget(self.annot_mgmt)

        self.table = AnnotationTableWidget(self.handEventsTableContainer)
        table_layout = self.handEventsTableContainer.layout()
        if table_layout is None:
            table_layout = QVBoxLayout(self.handEventsTableContainer)
            table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.addWidget(self.table)

        self.smart_widget = SmartSpottingWidget(self.smartWidgetContainer)
        smart_layout = self.smartWidgetContainer.layout()
        if smart_layout is None:
            smart_layout = QVBoxLayout(self.smartWidgetContainer)
            smart_layout.setContentsMargins(0, 0, 0, 0)
        smart_layout.addWidget(self.smart_widget)

        self.tabs.currentChanged.connect(self.tabSwitched.emit)


__all__ = [
    "LocalizationAnnotationPanel",
    "AnnotationTableModel",
    "AnnotationTableWidget",
]
