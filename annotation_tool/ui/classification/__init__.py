import math
import os
import sys

from PyQt6 import uic
from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path


class NativeDonutChart(QWidget):
    """
    Lightweight donut chart used to display smart-inference confidence.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(160, 160)
        self.setMouseTracking(True)

        self.data_dict = {}
        self.top_label = ""
        self.slices_info = []
        self.setVisible(False)

    def update_chart(self, top_label, conf_dict):
        self.top_label = top_label

        sorted_data = {top_label: conf_dict.get(top_label, 0.0)}
        for key, value in conf_dict.items():
            if key != top_label:
                sorted_data[key] = value

        self.data_dict = sorted_data
        self.repaint()
        self.setVisible(True)

    def paintEvent(self, event):
        if not self.data_dict:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        margin = 30
        rect = QRectF(margin, margin, self.width() - margin * 2, self.height() - margin * 2)
        pen_width = 35

        start_angle_qt = 90 * 16
        self.slices_info.clear()

        color_top = QColor("#4CAF50")
        colors_other = [
            QColor("#607D8B"),
            QColor("#78909C"),
            QColor("#546E7A"),
            QColor("#455A64"),
        ]
        color_idx = 0
        current_angle_deg = 0.0

        for label, prob in self.data_dict.items():
            span_deg = prob * 360
            span_angle_qt = int(round(-span_deg * 16))

            if span_angle_qt == 0:
                continue

            color = color_top if label == self.top_label else colors_other[color_idx % len(colors_other)]
            if label != self.top_label:
                color_idx += 1

            pen = QPen(color)
            pen.setWidth(pen_width)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, start_angle_qt, span_angle_qt)

            self.slices_info.append(
                {
                    "label": label,
                    "prob": prob,
                    "start_deg": current_angle_deg,
                    "end_deg": current_angle_deg + span_deg,
                }
            )

            start_angle_qt += span_angle_qt
            current_angle_deg += span_deg

        painter.setPen(QColor("white"))
        font = QFont("Arial", 12, QFont.Weight.Bold)
        painter.setFont(font)
        top_prob = self.data_dict.get(self.top_label, 0.0)
        text_rect = QRectF(0, 0, self.width(), self.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, f"{self.top_label}\n{top_prob*100:.1f}%")

    def mouseMoveEvent(self, event):
        if not self.data_dict:
            return

        pos = event.position()
        center_x = self.width() / 2
        center_y = self.height() / 2
        dx = pos.x() - center_x
        dy = pos.y() - center_y

        distance = math.sqrt(dx**2 + dy**2)
        radius = (self.width() - 60) / 2
        pen_width = 35

        if distance < (radius - pen_width / 2) or distance > (radius + pen_width / 2):
            QToolTip.hideText()
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad) + 90
        if angle_deg < 0:
            angle_deg += 360

        hovered_text = None
        for slice_info in self.slices_info:
            if slice_info["start_deg"] <= angle_deg <= slice_info["end_deg"]:
                hovered_text = f"{slice_info['label']}: {slice_info['prob']*100:.1f}%"
                break

        if hovered_text:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            QToolTip.showText(event.globalPosition().toPoint(), hovered_text, self)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            QToolTip.hideText()


class DynamicSingleLabelGroup(QWidget):
    value_changed = pyqtSignal(str, str)
    remove_category_signal = pyqtSignal(str)
    remove_label_signal = pyqtSignal(str, str)
    smart_infer_requested = pyqtSignal(str)
    smart_confirm_requested = pyqtSignal(str)
    smart_reject_requested = pyqtSignal(str)

    def __init__(self, head_name, definition, parent=None):
        super().__init__(parent)
        self.head_name = head_name
        self.definition = definition

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 2)
        self.layout.setSpacing(2)

        header_layout = QHBoxLayout()
        self.lbl_head = QLabel(head_name)
        self.lbl_head.setProperty("class", "group_head_lbl group_head_single")

        self.btn_smart_infer = QPushButton("Smart Inference")
        self.btn_smart_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_smart_infer.clicked.connect(lambda: self.smart_infer_requested.emit(self.head_name))

        self.btn_del_cat = QPushButton("×")
        self.btn_del_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_cat.setProperty("class", "icon_remove_btn")
        self.btn_del_cat.clicked.connect(lambda: self.remove_category_signal.emit(self.head_name))

        header_layout.addWidget(self.lbl_head)
        header_layout.addWidget(self.btn_smart_infer)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_del_cat)
        self.layout.addLayout(header_layout)

        self.radio_group = QButtonGroup(self)
        self.radio_group.setExclusive(True)
        self.radio_group.buttonClicked.connect(self._on_radio_clicked)

        self.radio_container = QWidget()
        self.radio_layout = QVBoxLayout(self.radio_container)
        self.radio_layout.setContentsMargins(5, 0, 0, 0)
        self.layout.addWidget(self.radio_container)
        self._smart_controls_by_label = {}

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(f"Add option to {head_name}...")
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.add_btn)
        self.layout.addLayout(input_layout)

        self.update_radios(definition.get("labels", []))

    def update_radios(self, labels):
        self._smart_controls_by_label = {}
        for btn in self.radio_group.buttons():
            self.radio_group.removeButton(btn)
            btn.deleteLater()

        while self.radio_layout.count():
            item = self.radio_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, label_text in enumerate(labels):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            rb = QRadioButton(label_text)
            rb.setProperty("class", "label_item")
            self.radio_group.addButton(rb, index)

            del_label_btn = QPushButton("×")
            del_label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_label_btn.setProperty("class", "icon_remove_btn")
            del_label_btn.clicked.connect(lambda _, lbl=label_text: self.remove_label_signal.emit(lbl, self.head_name))

            conf_btn = QPushButton("")
            conf_btn.setProperty("class", "smart_conf_btn")
            conf_btn.setCursor(Qt.CursorShape.ArrowCursor)
            conf_btn.setVisible(False)

            accept_btn = QPushButton("✓")
            accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            accept_btn.setProperty("class", "smart_accept_btn")
            accept_btn.setVisible(False)
            accept_btn.clicked.connect(lambda _, h=self.head_name: self.smart_confirm_requested.emit(h))

            reject_btn = QPushButton("✕")
            reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            reject_btn.setProperty("class", "smart_reject_btn")
            reject_btn.setVisible(False)
            reject_btn.clicked.connect(lambda _, h=self.head_name: self.smart_reject_requested.emit(h))

            row_layout.addWidget(rb)
            row_layout.addStretch()
            row_layout.addWidget(conf_btn)
            row_layout.addWidget(accept_btn)
            row_layout.addWidget(reject_btn)
            row_layout.addWidget(del_label_btn)
            self.radio_layout.addWidget(row_widget)
            self._smart_controls_by_label[label_text] = (conf_btn, accept_btn, reject_btn)

    def _on_radio_clicked(self, btn):
        self.value_changed.emit(self.head_name, btn.text())

    def get_checked_label(self):
        btn = self.radio_group.checkedButton()
        return btn.text() if btn else None

    def set_checked_label(self, label_text):
        if not label_text:
            btn = self.radio_group.checkedButton()
            if btn:
                self.radio_group.setExclusive(False)
                btn.setChecked(False)
                self.radio_group.setExclusive(True)
            return

        for btn in self.radio_group.buttons():
            if btn.text() == label_text:
                btn.setChecked(True)
                break

    def set_smart_state(self, predicted_label: str, confidence_score: float, is_smart: bool):
        for conf_btn, accept_btn, reject_btn in self._smart_controls_by_label.values():
            conf_btn.setVisible(False)
            accept_btn.setVisible(False)
            reject_btn.setVisible(False)

        if not is_smart:
            return

        controls = self._smart_controls_by_label.get(str(predicted_label or ""))
        if controls is None:
            return

        self.set_checked_label(str(predicted_label or ""))

        try:
            pct = float(confidence_score or 0.0) * 100.0
        except Exception:
            pct = 0.0
        conf_btn, accept_btn, reject_btn = controls
        conf_btn.setText(f"{pct:.1f}%")
        conf_btn.setVisible(True)
        accept_btn.setVisible(True)
        reject_btn.setVisible(True)

    def get_row_smart_widgets(self, label_text: str):
        return self._smart_controls_by_label.get(str(label_text or ""))


class DynamicMultiLabelGroup(QWidget):
    value_changed = pyqtSignal(str, list)
    remove_category_signal = pyqtSignal(str)
    remove_label_signal = pyqtSignal(str, str)
    smart_infer_requested = pyqtSignal(str)
    smart_confirm_requested = pyqtSignal(str)
    smart_reject_requested = pyqtSignal(str)

    def __init__(self, head_name, definition, parent=None):
        super().__init__(parent)
        self.head_name = head_name
        self.definition = definition

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 5)

        header_layout = QHBoxLayout()
        self.lbl_head = QLabel(head_name)
        self.lbl_head.setProperty("class", "group_head_lbl group_head_multi")

        self.btn_smart_infer = QPushButton("Smart Inference")
        self.btn_smart_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_smart_infer.clicked.connect(lambda: self.smart_infer_requested.emit(self.head_name))

        self.btn_del_cat = QPushButton("×")
        self.btn_del_cat.setProperty("class", "icon_remove_btn")
        self.btn_del_cat.clicked.connect(lambda: self.remove_category_signal.emit(self.head_name))

        header_layout.addWidget(self.lbl_head)
        header_layout.addWidget(self.btn_smart_infer)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_del_cat)
        self.layout.addLayout(header_layout)

        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        self.checkbox_layout.setContentsMargins(5, 0, 0, 0)
        self.layout.addWidget(self.checkbox_container)

        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Add option...")
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.add_btn)
        self.layout.addLayout(input_layout)

        self.checkboxes = {}
        self._smart_controls_by_label = {}
        self.update_checkboxes(definition.get("labels", []))

    def update_checkboxes(self, labels):
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.checkboxes = {}
        self._smart_controls_by_label = {}

        for label_name in sorted(list(set(labels))):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            cb = QCheckBox(label_name)
            cb.setProperty("class", "label_item")
            cb.clicked.connect(self._on_box_clicked)
            self.checkboxes[label_name] = cb

            del_label_btn = QPushButton("×")
            del_label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_label_btn.setProperty("class", "icon_remove_btn")
            del_label_btn.clicked.connect(lambda _, lbl=label_name: self.remove_label_signal.emit(lbl, self.head_name))

            conf_btn = QPushButton("")
            conf_btn.setProperty("class", "smart_conf_btn")
            conf_btn.setCursor(Qt.CursorShape.ArrowCursor)
            conf_btn.setVisible(False)

            accept_btn = QPushButton("✓")
            accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            accept_btn.setProperty("class", "smart_accept_btn")
            accept_btn.setVisible(False)
            accept_btn.clicked.connect(lambda _, h=self.head_name: self.smart_confirm_requested.emit(h))

            reject_btn = QPushButton("✕")
            reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            reject_btn.setProperty("class", "smart_reject_btn")
            reject_btn.setVisible(False)
            reject_btn.clicked.connect(lambda _, h=self.head_name: self.smart_reject_requested.emit(h))

            row_layout.addWidget(cb)
            row_layout.addStretch()
            row_layout.addWidget(conf_btn)
            row_layout.addWidget(accept_btn)
            row_layout.addWidget(reject_btn)
            row_layout.addWidget(del_label_btn)
            self.checkbox_layout.addWidget(row_widget)
            self._smart_controls_by_label[label_name] = (conf_btn, accept_btn, reject_btn)

    def _on_box_clicked(self):
        self.value_changed.emit(self.head_name, self.get_checked_labels())

    def get_checked_labels(self):
        return [cb.text() for cb in self.checkboxes.values() if cb.isChecked()]

    def set_checked_labels(self, labels):
        if labels is None:
            normalized = []
        elif isinstance(labels, (list, tuple, set)):
            normalized = [str(v) for v in labels]
        else:
            normalized = [str(labels)]
        self.blockSignals(True)
        for text, cb in self.checkboxes.items():
            cb.setChecked(text in normalized)
        self.blockSignals(False)

    def set_smart_state(self, predicted_label: str, confidence_score: float, is_smart: bool):
        for conf_btn, accept_btn, reject_btn in self._smart_controls_by_label.values():
            conf_btn.setVisible(False)
            accept_btn.setVisible(False)
            reject_btn.setVisible(False)

        if not is_smart:
            return

        controls = self._smart_controls_by_label.get(str(predicted_label or ""))
        if controls is None:
            return

        self.set_checked_labels([str(predicted_label or "")])

        try:
            pct = float(confidence_score or 0.0) * 100.0
        except Exception:
            pct = 0.0
        conf_btn, accept_btn, reject_btn = controls
        conf_btn.setText(f"{pct:.1f}%")
        conf_btn.setVisible(True)
        accept_btn.setVisible(True)
        reject_btn.setVisible(True)

    def get_row_smart_widgets(self, label_text: str):
        return self._smart_controls_by_label.get(str(label_text or ""))


class ClassificationAnnotationPanel(QWidget):
    add_head_clicked = pyqtSignal(str)
    remove_head_clicked = pyqtSignal(str)
    style_mode_changed = pyqtSignal(str)

    head_smart_infer_requested = pyqtSignal(str)
    head_smart_confirm_requested = pyqtSignal(str)
    head_smart_reject_requested = pyqtSignal(str)
    confirm_infer_requested = pyqtSignal(dict)
    batch_confirm_requested = pyqtSignal(dict)

    annotation_saved = pyqtSignal(dict)
    batch_run_requested = pyqtSignal(int, int)

    hand_clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "classification", "classification_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load ClassificationAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.is_batch_mode_active = False
        self.pending_batch_results = {}
        self.full_action_names = []
        self.label_groups = {}
        self._smart_state_by_head = {}

        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setStyleSheet(
            """
            QTabBar::tab {
                padding-left: 3px;
                padding-right: 3px;
                padding-top: 5px;
                padding-bottom: 5px;
                font-size: 13px;
                min-width: 0px;
                max-width: 1000px;
            }
            """
        )

        self.add_head_btn.clicked.connect(lambda: self.add_head_clicked.emit(self.new_head_edit.text()))
        # Smart inference is now per head in dynamic group headers.
        self.confirm_btn.setVisible(False)
        self.confirm_btn.setEnabled(False)
        self.clear_sel_btn.clicked.connect(self.on_clear_clicked)

        self._remove_disabled_tabs()

        self.chart_widget = NativeDonutChart(self)
        self.chart_widget.setVisible(False)

        self._configure_train_defaults()
        self.clear_dynamic_labels()
        self.manual_box.setEnabled(False)
        self._update_confirm_button_state()

    def _remove_disabled_tabs(self):
        disabled_tabs = [getattr(self, "smart_box", None), getattr(self, "train_box", None)]
        for tab_widget in disabled_tabs:
            if tab_widget is None:
                continue
            for idx in reversed(range(self.tabs.count())):
                if self.tabs.widget(idx) is tab_widget:
                    self.tabs.removeTab(idx)
                    break

    def _configure_train_defaults(self):
        self.spin_epochs.clear()
        self.spin_epochs.addItems(["1", "5", "10", "20", "50", "100"])
        self.spin_batch.clear()
        self.spin_batch.addItems(["1", "2", "4", "8", "16"])
        self.combo_device.clear()
        self.combo_device.addItems(["cpu", "mps (Metal)", "cuda"])
        if sys.platform == "darwin":
            self.combo_device.setCurrentText("mps (Metal)")
        self.spin_workers.clear()
        self.spin_workers.addItems(["0", "2", "4"])

        self.btn_start_train.setStyleSheet(
            """
            QPushButton {
                background-color: #007bff;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0069d9; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
            """
        )

        self.lbl_train_status.setText("Ready to train")
        self.lbl_train_status.setStyleSheet("color: #4A90E2; font-weight: bold; margin-top: 5px;")
        self.lbl_train_status.setVisible(False)

        self.train_progress.setRange(0, 100)
        self.train_progress.setValue(0)
        self.train_progress.setVisible(False)

        self.train_console.setReadOnly(True)
        self.train_console.setPlaceholderText("Training logs will appear here...")
        self.train_console.setStyleSheet(
            "background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New'; font-size: 11px;"
        )

        self.btn_stop_train.setEnabled(False)

    def _toggle_batch_widget(self):
        self.batch_input_widget.setVisible(not self.batch_input_widget.isVisible())

    def _on_run_batch_clicked(self):
        start_idx = self.spin_start.currentIndex()
        if start_idx < 0:
            return
        end_idx = start_idx + self.spin_end.currentIndex()
        if end_idx >= start_idx:
            self.batch_run_requested.emit(start_idx, end_idx)

    def _validate_batch_range(self):
        start_idx = self.spin_start.currentIndex()
        if start_idx < 0:
            return

        current_end_text = self.spin_end.currentText()
        self.spin_end.blockSignals(True)
        self.spin_end.clear()

        valid_end_items = self.full_action_names[start_idx:]
        self.spin_end.addItems(valid_end_items)

        if current_end_text in valid_end_items:
            self.spin_end.setCurrentText(current_end_text)
        else:
            self.spin_end.setCurrentIndex(0)

        self.spin_end.blockSignals(False)

    def on_confirm_clicked(self):
        return

    def _update_confirm_button_state(self):
        self.confirm_btn.setVisible(False)

    def on_clear_clicked(self):
        self.hand_clear_requested.emit()

    def reset_smart_inference(self):
        self.is_batch_mode_active = False
        self.pending_batch_results = {}
        self.chart_widget.setVisible(False)

    def reset_train_ui(self):
        self.train_progress.setValue(0)
        self.train_progress.setVisible(False)
        self.lbl_train_status.setText("Ready to train")
        self.lbl_train_status.setVisible(False)
        self.train_console.clear()
        self.btn_start_train.setEnabled(True)
        self.btn_stop_train.setEnabled(False)

    def update_action_list(self, action_names: list):
        self.full_action_names = list(action_names or [])
        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)
        self.spin_start.clear()
        self.spin_end.clear()
        self.spin_start.addItems(self.full_action_names)
        self.spin_end.addItems(self.full_action_names)
        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)
        if self.full_action_names:
            self._validate_batch_range()

    def show_inference_loading(self, is_loading: bool):
        _ = is_loading

    def display_inference_result(self, target_head: str, predicted_label: str, conf_dict: dict):
        score = 0.0
        if isinstance(conf_dict, dict):
            try:
                score = float(conf_dict.get(predicted_label, 0.0) or 0.0)
            except Exception:
                score = 0.0
        self.set_head_smart_state(target_head, predicted_label, score, True)

    def display_batch_inference_result(self, result_text: str, batch_predictions: dict):
        _ = (result_text, batch_predictions)

    def clear_dynamic_labels(self):
        self.setup_dynamic_labels({})

    def setup_dynamic_labels(self, label_definitions):
        while self.label_container_layout.count():
            item = self.label_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.label_groups = {}
        for head, definition in label_definitions.items():
            group_type = definition.get("type", "single_label")
            if group_type == "single_label":
                group = DynamicSingleLabelGroup(head, definition)
            else:
                group = DynamicMultiLabelGroup(head, definition)

            group.remove_category_signal.connect(self.remove_head_clicked.emit)
            group.smart_infer_requested.connect(self.head_smart_infer_requested.emit)
            group.smart_confirm_requested.connect(self.head_smart_confirm_requested.emit)
            group.smart_reject_requested.connect(self.head_smart_reject_requested.emit)
            self.label_container_layout.addWidget(group)
            self.label_groups[head] = group

        self.label_container_layout.addStretch()

    def set_annotation(self, data):
        self.reset_smart_inference()
        if not data:
            data = {}

        for head, group in self.label_groups.items():
            value = data.get(head)
            if hasattr(group, "set_checked_label"):
                group.set_checked_label(value)
            elif hasattr(group, "set_checked_labels"):
                group.set_checked_labels(value)
            if hasattr(group, "set_smart_state"):
                group.set_smart_state("", 0.0, False)

    def get_annotation(self):
        result = {}
        for head, group in self.label_groups.items():
            if hasattr(group, "get_checked_label"):
                value = group.get_checked_label()
                if value:
                    result[head] = value
            elif hasattr(group, "get_checked_labels"):
                values = group.get_checked_labels()
                if values:
                    result[head] = values
        return result

    def clear_selection(self):
        for group in self.label_groups.values():
            if hasattr(group, "set_checked_label"):
                group.set_checked_label(None)
            elif hasattr(group, "set_checked_labels"):
                group.set_checked_labels([])

    def set_head_smart_state(self, head: str, predicted_label: str, confidence_score: float, is_smart: bool):
        group = self.label_groups.get(head)
        if not group or not hasattr(group, "set_smart_state"):
            return
        group.set_smart_state(str(predicted_label or ""), float(confidence_score or 0.0), bool(is_smart))

    def get_head_row_smart_widgets(self, head: str, label_text: str):
        group = self.label_groups.get(head)
        if not group or not hasattr(group, "get_row_smart_widgets"):
            return None
        return group.get_row_smart_widgets(label_text)
