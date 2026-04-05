import math
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QGroupBox, QLineEdit, QScrollArea, QFrame, QProgressBar, QToolTip, QTextEdit, QTabWidget, QComboBox
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QCursor
import sys

from .dynamic_widgets import DynamicSingleLabelGroup, DynamicMultiLabelGroup

class NativeDonutChart(QWidget):
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
        for k, v in conf_dict.items():
            if k != top_label:
                sorted_data[k] = v
                
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
        colors_other = [QColor("#607D8B"), QColor("#78909C"), QColor("#546E7A"), QColor("#455A64")]
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

            self.slices_info.append({
                "label": label,
                "prob": prob,
                "start_deg": current_angle_deg,
                "end_deg": current_angle_deg + span_deg
            })

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
        
        if distance < (radius - pen_width/2) or distance > (radius + pen_width/2):
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


class ClassificationEventEditor(QWidget):
    add_head_clicked = pyqtSignal(str)
    remove_head_clicked = pyqtSignal(str)
    style_mode_changed = pyqtSignal(str)
    
    smart_infer_requested = pyqtSignal() 
    confirm_infer_requested = pyqtSignal(dict) 
    
    batch_confirm_requested = pyqtSignal(dict)

    annotation_saved = pyqtSignal(dict)
    smart_confirm_requested = pyqtSignal()  # [NEW] Signal emitted when confirming from the Smart Tab
    batch_run_requested = pyqtSignal(int, int)

    # [NEW] Signals for tab-aware clearing
    hand_clear_requested = pyqtSignal()
    smart_clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)
        layout = QVBoxLayout(self)
        
        self.is_batch_mode_active = False
        self.pending_batch_results = {}
        
        # 1. Undo/Redo removed (moved to menu bar)
        
        # 2. Task Information
        self.task_label = QLabel("Task: N/A")
        self.task_label.setProperty("class", "editor_task_lbl")
        layout.addWidget(self.task_label)

        # 3. Schema Editor
        schema_box = QGroupBox("Category Editor")
        schema_layout = QHBoxLayout(schema_box)
        self.new_head_edit = QLineEdit()
        self.new_head_edit.setPlaceholderText("New Category Name...")
        self.add_head_btn = QPushButton("Add Head")
        self.add_head_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_head_btn.clicked.connect(lambda: self.add_head_clicked.emit(self.new_head_edit.text()))
        schema_layout.addWidget(self.new_head_edit)
        schema_layout.addWidget(self.add_head_btn)
        layout.addWidget(schema_box)

        # [NEW] Create QTabWidget to hold both annotation modes
        self.tabs = QTabWidget()

        # 1. [Core] Completely disable elide mode to prevent text from becoming "..."
        self.tabs.setElideMode(Qt.TextElideMode.ElideNone)

        # 2. Force the tab bar not to expand automatically, making it only occupy the space required by the text
        self.tabs.tabBar().setExpanding(False)

        # 3. Optimize stylesheet: remove min-width restrictions and set extremely narrow Padding
        self.tabs.setStyleSheet("""
            QTabBar::tab {
                /* Set small left and right margins to ensure text is compact and visible */
                padding-left: 3px;
                padding-right: 3px;
                padding-top: 5px;
                padding-bottom: 5px;
                
                /* Keep font size moderate */
                font-size: 13px; 
                
                /* Ensure there are no hard limits on minimum and maximum width */
                min-width: 0px;
                max-width: 1000px; 
            }
        """)

        self.tabs.setObjectName("annotation_tabs")
        layout.addWidget(self.tabs, 1) # Add tabs to main layout with stretch factor 1

        # --- 4. Hand Annotation Tab ---
        # Changed from QGroupBox to QWidget to fit seamlessly inside the Tab
        self.manual_box = QWidget() 
        self.manual_box.setEnabled(False) 
        manual_layout = QVBoxLayout(self.manual_box)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        self.label_container = QWidget()
        self.label_container_layout = QVBoxLayout(self.label_container)
        self.label_container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        scroll.setWidget(self.label_container)
        manual_layout.addWidget(scroll)
        
        # Add the manual widget as the first tab
        self.tabs.addTab(self.manual_box, "Hand Annotation")

        # --- 5. Smart Annotation Tab ---
        # Changed from QGroupBox to QWidget to fit seamlessly inside the Tab
        self.smart_box = QWidget() 
        smart_layout = QVBoxLayout(self.smart_box)

        # [NEW] Force all items in the smart tab to align to the top 
        # This prevents the inference buttons from jumping around
        smart_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Two Buttons for Inference
        btn_h_layout = QHBoxLayout()
        self.btn_smart_infer = QPushButton("Single Inference")
        self.btn_smart_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_smart_infer.clicked.connect(self.smart_infer_requested.emit)
        
        self.btn_batch_infer = QPushButton("Batch Inference")
        self.btn_batch_infer.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_batch_infer.clicked.connect(lambda: self.batch_input_widget.setVisible(not self.batch_input_widget.isVisible()))

        btn_h_layout.addWidget(self.btn_smart_infer)
        btn_h_layout.addWidget(self.btn_batch_infer)
        smart_layout.addLayout(btn_h_layout)

        # Input Box for Batch Inference
        self.batch_input_widget = QWidget()
        h_batch = QHBoxLayout(self.batch_input_widget)
        h_batch.setContentsMargins(0, 5, 0, 5)
        # [NEW] Add descriptive labels for the Start and End comboboxes
        self.lbl_start = QLabel("Start:")
        self.spin_start = QComboBox()
        
        self.lbl_end = QLabel("End:")
        self.spin_end = QComboBox()
        
        self.btn_run_batch = QPushButton("Run")
        self.btn_run_batch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_run_batch.clicked.connect(self._on_run_batch_clicked)
        
        # [MODIFIED] Add the labels and comboboxes to the horizontal layout in order
        h_batch.addWidget(self.lbl_start)
        h_batch.addWidget(self.spin_start)
        h_batch.addWidget(self.lbl_end)
        h_batch.addWidget(self.spin_end)
        h_batch.addWidget(self.btn_run_batch)
        
        self.batch_input_widget.setVisible(False)


        # [NEW] Connect validation signals to enforce i <= j rule
        self.spin_start.currentIndexChanged.connect(self._validate_batch_range)
        #self.spin_end.currentIndexChanged.connect(self._validate_batch_range)
        
        self.infer_progress = QProgressBar()
        self.infer_progress.setRange(0, 0) 
        self.infer_progress.setVisible(False)
        
        self.chart_widget = NativeDonutChart()
        
        self.batch_result_text = QTextEdit()
        self.batch_result_text.setReadOnly(True)
        self.batch_result_text.setVisible(False)
        self.batch_result_text.setMinimumHeight(120)
        
        smart_layout.addWidget(self.batch_input_widget)
        smart_layout.addWidget(self.infer_progress)
        smart_layout.addWidget(self.chart_widget, alignment=Qt.AlignmentFlag.AlignCenter)
        smart_layout.addWidget(self.batch_result_text)
        
        # Add the smart widget as the second tab
        self.tabs.addTab(self.smart_box, "Smart Annotation")

        # --- 7. Train Tab [RE-DESIGNED] ---
        self.train_box = QWidget()
        train_main_layout = QVBoxLayout(self.train_box)
        train_main_layout.setContentsMargins(5, 5, 5, 5)
        train_main_layout.setSpacing(10)

        # Use a scrolling area to prevent incomplete display when there are too many parameters
        train_scroll = QScrollArea()
        train_scroll.setWidgetResizable(True)
        train_scroll.setFrameShape(QFrame.Shape.NoFrame)
        train_scroll_content = QWidget()
        train_layout = QVBoxLayout(train_scroll_content)
        train_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # A. Training Hyperparameters Group
        hyper_group = QGroupBox("Hyperparameters")
        hyper_form = QVBoxLayout(hyper_group) # Wrap form rows using a vertical layout
        
        # Encapsulate a simple form row function
        def add_form_row(label_text, widget):
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setFixedWidth(80)
            row.addWidget(lbl)
            row.addWidget(widget)
            return row

        self.spin_epochs = QComboBox()
        self.spin_epochs.addItems(["1", "5", "10", "20", "50", "100"])
        self.spin_epochs.setEditable(True)
        hyper_form.addLayout(add_form_row("Epochs:", self.spin_epochs))

        self.edit_lr = QLineEdit("0.0001")
        hyper_form.addLayout(add_form_row("LR:", self.edit_lr))

        self.spin_batch = QComboBox()
        self.spin_batch.addItems(["1", "2", "4", "8", "16"])
        self.spin_batch.setEditable(True)
        hyper_form.addLayout(add_form_row("Batch:", self.spin_batch))

        train_layout.addWidget(hyper_group)

        # B. Hardware Settings Group (Optimized for Mac M1)
        device_group = QGroupBox("Execution")
        device_form = QVBoxLayout(device_group)

        self.combo_device = QComboBox()
        # Add mps option for M1
        self.combo_device.addItems(["cpu", "mps (Metal)", "cuda"]) 
        if sys.platform == "darwin": 
            self.combo_device.setCurrentText("mps (Metal)")
        device_form.addLayout(add_form_row("Device:", self.combo_device))

        self.spin_workers = QComboBox()
        self.spin_workers.addItems(["0", "2", "4"])
        device_form.addLayout(add_form_row("Workers:", self.spin_workers))

        train_layout.addWidget(device_group)

        # C. Training Action & Monitor
        h_train_btns = QHBoxLayout() # Create horizontal layout
        
        # 1. Start Training Button
        self.btn_start_train = QPushButton("Start Training")
        self.btn_start_train.setMinimumHeight(40)
        self.btn_start_train.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start_train.setStyleSheet("""
            QPushButton {
                background-color: #007bff; 
                color: white; 
                font-weight: bold; 
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #0069d9; }
            QPushButton:disabled { background-color: #cccccc; color: #666666; }
        """)

        # 2. Stop Training Button [NEW]
        self.btn_stop_train = QPushButton("Stop Training")
        self.btn_stop_train.setMinimumHeight(40)
        self.btn_stop_train.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_stop_train.setEnabled(False) # Initially unclickable
        # Style consistent with Clear Selection (Standard button style)
        self.btn_stop_train.setProperty("class", "editor_control_btn") 

        h_train_btns.addWidget(self.btn_start_train, 2) # Start takes up more space
        h_train_btns.addWidget(self.btn_stop_train, 1)
        
        # Followed by status label and progress bar
        self.lbl_train_status = QLabel("Ready to train")
       

        self.lbl_train_status = QLabel("Ready to train")
        self.lbl_train_status.setStyleSheet("color: #4A90E2; font-weight: bold; margin-top: 5px;")
        self.lbl_train_status.setVisible(False) 
        

        self.train_progress = QProgressBar()
        self.train_progress.setRange(0, 100) 
        self.train_progress.setValue(0)
        self.train_progress.setVisible(False)
        
        self.train_console = QTextEdit()
        self.train_console.setReadOnly(True)
        self.train_console.setPlaceholderText("Training logs will appear here...")
        self.train_console.setMinimumHeight(150)
        self.train_console.setStyleSheet("background-color: #1e1e1e; color: #d4d4d4; font-family: 'Courier New'; font-size: 11px;")

        train_layout.addLayout(h_train_btns) 
        train_layout.addWidget(self.lbl_train_status)
        train_layout.addWidget(self.train_progress)
        train_layout.addWidget(self.train_console)

        train_scroll.setWidget(train_scroll_content)
        train_main_layout.addWidget(train_scroll)

        self.tabs.addTab(self.train_box, "Train")

        # --- 6. Bottom Confirm Buttons (Fixed Outside Tabs) ---
        btn_row = QHBoxLayout()
        self.confirm_btn = QPushButton("Confirm Annotation")
        self.clear_sel_btn = QPushButton("Clear Selection")
        self.confirm_btn.setProperty("class", "editor_save_btn")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_sel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        self.confirm_btn.clicked.connect(self.on_confirm_clicked)
        # [NEW] Route the clear button internally
        self.clear_sel_btn.clicked.connect(self.on_clear_clicked)

        btn_row.addWidget(self.confirm_btn)
        btn_row.addWidget(self.clear_sel_btn)
        layout.addLayout(btn_row) # Add strictly to the main vertical layout, remaining at the bottom
        
        self.label_groups = {}

    def _on_run_batch_clicked(self):
        try:
            start_idx = int(self.spin_start.text().strip())
            end_idx = int(self.spin_end.text().strip())
            self.batch_run_requested.emit(start_idx, end_idx)
        except ValueError:
            pass 


    def on_confirm_clicked(self):
        """[MODIFIED] Route confirm action based on the active tab."""
        active_tab_idx = self.tabs.currentIndex()
        
        if active_tab_idx == 0:
            # --- Hand Annotation Confirmation ---
            data = {}
            for head, group in self.label_groups.items():
                if hasattr(group, 'get_checked_label'):
                    val = group.get_checked_label()
                    if val: data[head] = val
                elif hasattr(group, 'get_checked_labels'):
                    val = group.get_checked_labels()
                    if val: data[head] = val
            self.annotation_saved.emit(data)
            
        elif active_tab_idx == 1:
            # --- Smart Annotation Confirmation ---
            self.smart_confirm_requested.emit()
    
    def on_clear_clicked(self):
        """[NEW] Route clear action based on the active tab."""
        active_tab_idx = self.tabs.currentIndex()
        if active_tab_idx == 0:
            self.hand_clear_requested.emit()
        elif active_tab_idx == 1:
            self.smart_clear_requested.emit()

    # [MODIFIED] Hide the batch input box upon confirmation or action switch
    def reset_smart_inference(self):
        self.is_batch_mode_active = False
        self.chart_widget.setVisible(False)
        self.batch_result_text.setVisible(False)
        self.btn_smart_infer.setEnabled(True)
        self.btn_batch_infer.setEnabled(True)
        self.infer_progress.setVisible(False)
        
        # Ensures Run Batch dropdowns disappear after Confirm or switching videos
        self.batch_input_widget.setVisible(False)

    def reset_train_ui(self):
        self.train_progress.setValue(0)
        self.train_progress.setVisible(False)
        
        self.lbl_train_status.setText("Ready to train")
        self.lbl_train_status.setVisible(False)
        
        self.train_console.clear()
        
        self.btn_start_train.setEnabled(True)

    # [MODIFIED] Save the full list and initialize the dropdowns
    def update_action_list(self, action_names: list):
        self.full_action_names = action_names
        
        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)
        
        self.spin_start.clear()
        self.spin_end.clear()
        
        self.spin_start.addItems(self.full_action_names)
        self.spin_end.addItems(self.full_action_names)
        
        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)

    # [MODIFIED] Dynamically update the second dropdown to only show items from index i onwards
    def _validate_batch_range(self):
        start_idx = self.spin_start.currentIndex()
        if start_idx < 0: return
        
        current_end_text = self.spin_end.currentText()
        
        self.spin_end.blockSignals(True)
        self.spin_end.clear()
        
        # Only add items starting from the selected 'start_idx'
        valid_end_items = self.full_action_names[start_idx:]
        self.spin_end.addItems(valid_end_items)
        
        # Attempt to restore the previous selection if it's still in the valid range
        if current_end_text in valid_end_items:
            self.spin_end.setCurrentText(current_end_text)
        else:
            self.spin_end.setCurrentIndex(0)
            
        self.spin_end.blockSignals(False)

    # [MODIFIED] Calculate absolute end index based on dynamic relative index
    def _on_run_batch_clicked(self):
        start_idx = self.spin_start.currentIndex()
        
        # Since spin_end only contains items from start_idx onwards, 
        # its absolute index is its relative index + start_idx
        end_idx = start_idx + self.spin_end.currentIndex()
        
        if start_idx >= 0 and end_idx >= start_idx:
            self.batch_run_requested.emit(start_idx, end_idx)

    def show_inference_loading(self, is_loading: bool):
        self.btn_smart_infer.setEnabled(not is_loading)
        self.btn_batch_infer.setEnabled(not is_loading)
        self.infer_progress.setVisible(is_loading)
        if is_loading:
            self.chart_widget.setVisible(False)
            self.batch_result_text.setVisible(False)

    def display_inference_result(self, target_head: str, predicted_label: str, conf_dict: dict):
        self.show_inference_loading(False)
        self.is_batch_mode_active = False
        self.chart_widget.update_chart(predicted_label, conf_dict)
                
    def display_batch_inference_result(self, result_text: str, batch_predictions: dict):
        self.show_inference_loading(False)
        self.is_batch_mode_active = True
        self.pending_batch_results = batch_predictions
        self.chart_widget.setVisible(False)
        self.batch_result_text.setText(result_text)
        self.batch_result_text.setVisible(True)

    def setup_dynamic_labels(self, label_definitions):
        while self.label_container_layout.count():
            item = self.label_container_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.label_groups = {}

        for head, defn in label_definitions.items():
            l_type = defn.get('type', 'single_label')
            if l_type == 'single_label':
                group = DynamicSingleLabelGroup(head, defn)
            else:
                group = DynamicMultiLabelGroup(head, defn)
            
            group.remove_category_signal.connect(self.remove_head_clicked.emit)
            self.label_container_layout.addWidget(group)
            self.label_groups[head] = group
        
        self.label_container_layout.addStretch()

    def set_annotation(self, data):
        self.reset_smart_inference()
        
        if not data: data = {}
        for head, group in self.label_groups.items():
            val = data.get(head)
            if hasattr(group, 'set_checked_label'):
                group.set_checked_label(val)
            elif hasattr(group, 'set_checked_labels'):
                group.set_checked_labels(val)

    def get_annotation(self):
        result = {}
        for head, group in self.label_groups.items():
            if hasattr(group, 'get_checked_label'):
                val = group.get_checked_label()
                if val: result[head] = val
            elif hasattr(group, 'get_checked_labels'):
                vals = group.get_checked_labels()
                if vals: result[head] = vals
        return result

    def clear_selection(self):
        # [MODIFIED] Keep the Donut Chart visible even if the user clears hand annotations.
        # self.reset_smart_inference()        
        for group in self.label_groups.values():
            if hasattr(group, 'set_checked_label'):
                group.set_checked_label(None)
            elif hasattr(group, 'set_checked_labels'):
                group.set_checked_labels([])