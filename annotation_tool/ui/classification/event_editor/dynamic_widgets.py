from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QLineEdit, QButtonGroup, QRadioButton, QCheckBox
)
from PyQt6.QtCore import pyqtSignal, Qt

class DynamicSingleLabelGroup(QWidget):
    value_changed = pyqtSignal(str, str) # head, selected_label
    remove_category_signal = pyqtSignal(str) # head
    remove_label_signal = pyqtSignal(str, str) # label, head

    def __init__(self, head_name, definition, parent=None):
        super().__init__(parent)
        self.head_name = head_name
        self.definition = definition 
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 2)
        self.layout.setSpacing(2)
        
        # Header
        header_layout = QHBoxLayout()
        self.lbl_head = QLabel(head_name)
        self.lbl_head.setProperty("class", "group_head_lbl group_head_single")
        
        self.btn_del_cat = QPushButton("×")
        self.btn_del_cat.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_del_cat.setProperty("class", "icon_remove_btn")
        self.btn_del_cat.clicked.connect(lambda: self.remove_category_signal.emit(self.head_name))
        
        header_layout.addWidget(self.lbl_head)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_del_cat)
        self.layout.addLayout(header_layout)
        
        # Radio Group
        self.radio_group = QButtonGroup(self)
        self.radio_group.setExclusive(True)
        self.radio_container = QWidget()
        self.radio_layout = QVBoxLayout(self.radio_container)
        self.radio_layout.setContentsMargins(5, 0, 0, 0)
        self.layout.addWidget(self.radio_container)
        
        # Input for new label
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(f"Add option to {head_name}...")
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.add_btn)
        self.layout.addLayout(input_layout)

        # Initial Population
        self.update_radios(definition.get('labels', []))
        self.radio_group.buttonClicked.connect(self._on_radio_clicked)

    def update_radios(self, labels):
        for btn in self.radio_group.buttons():
            self.radio_group.removeButton(btn)
            btn.deleteLater()
            
        while self.radio_layout.count():
            item = self.radio_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        for i, lbl_text in enumerate(labels):
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            
            rb = QRadioButton(lbl_text)
            self.radio_group.addButton(rb, i)
            rb.setProperty("class", "label_item")
            
            del_label_btn = QPushButton("×")
            del_label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_label_btn.setProperty("class", "icon_remove_btn")
            del_label_btn.clicked.connect(lambda _, l=lbl_text: self.remove_label_signal.emit(l, self.head_name))
            
            row_layout.addWidget(rb)
            row_layout.addStretch()
            row_layout.addWidget(del_label_btn)
            self.radio_layout.addWidget(row_widget)

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
                btn.setChecked(True); break

class DynamicMultiLabelGroup(QWidget):
    value_changed = pyqtSignal(str, list)
    remove_category_signal = pyqtSignal(str)
    remove_label_signal = pyqtSignal(str, str) 

    def __init__(self, head_name, definition, parent=None):
        super().__init__(parent)
        self.head_name = head_name
        self.definition = definition
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 2, 0, 5)
        
        # Header
        header_layout = QHBoxLayout()
        self.lbl_head = QLabel(head_name)
        self.lbl_head.setProperty("class", "group_head_lbl group_head_multi")
        
        self.btn_del_cat = QPushButton("×")
        self.btn_del_cat.setProperty("class", "icon_remove_btn")
        self.btn_del_cat.clicked.connect(lambda: self.remove_category_signal.emit(self.head_name))
        
        header_layout.addWidget(self.lbl_head)
        header_layout.addStretch()
        header_layout.addWidget(self.btn_del_cat)
        self.layout.addLayout(header_layout)
        
        self.checkbox_container = QWidget()
        self.checkbox_layout = QVBoxLayout(self.checkbox_container)
        self.checkbox_layout.setContentsMargins(5, 0, 0, 0)
        self.layout.addWidget(self.checkbox_container)
        
        # Input
        input_layout = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText(f"Add option...")
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(30, 30)
        
        input_layout.addWidget(self.input_field)
        input_layout.addWidget(self.add_btn)
        self.layout.addLayout(input_layout)
        
        self.checkboxes = {} 
        self.update_checkboxes(definition.get('labels', []))

    def update_checkboxes(self, new_types):
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        self.checkboxes.clear()
        
        for type_name in sorted(list(set(new_types))): 
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)

            cb = QCheckBox(type_name)
            cb.clicked.connect(self._on_box_clicked)
            self.checkboxes[type_name] = cb
            cb.setProperty("class", "label_item")
            
            del_label_btn = QPushButton("×")
            del_label_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_label_btn.setProperty("class", "icon_remove_btn")
            del_label_btn.clicked.connect(lambda _, n=type_name: self.remove_label_signal.emit(n, self.head_name))

            row_layout.addWidget(cb)
            row_layout.addStretch()
            row_layout.addWidget(del_label_btn)
            self.checkbox_layout.addWidget(row_widget)
            
    def _on_box_clicked(self):
        self.value_changed.emit(self.head_name, self.get_checked_labels())

    def get_checked_labels(self):
        return [cb.text() for cb in self.checkboxes.values() if cb.isChecked()]

    def set_checked_labels(self, label_list):
        self.blockSignals(True)
        if not label_list: label_list = []
        for text, cb in self.checkboxes.items():
            cb.setChecked(text in label_list)
        self.blockSignals(False)