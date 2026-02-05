from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, 
    QTextEdit, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal

class DescriptionEventEditor(QWidget):
    """
    Right Panel for Description Mode.
    Single text area for Q&A style descriptions.
    """
    
    # Signals
    undo_clicked = pyqtSignal()
    redo_clicked = pyqtSignal()
    confirm_clicked = pyqtSignal()      # Save changes
    clear_clicked = pyqtSignal()        # Clear text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(350) 
        
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(10)
        self.layout.setContentsMargins(15, 15, 15, 15)
        
        # --- 1. Undo/Redo Controls ---
        h_undo = QHBoxLayout()
        self.undo_btn = QPushButton("Undo")
        self.redo_btn = QPushButton("Redo")
        
        for btn in [self.undo_btn, self.redo_btn]:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setEnabled(False)
            btn.setProperty("class", "editor_control_btn")
            
        self.undo_btn.clicked.connect(self.undo_clicked.emit)
        self.redo_btn.clicked.connect(self.redo_clicked.emit)
            
        h_undo.addWidget(self.undo_btn)
        h_undo.addWidget(self.redo_btn)
        self.layout.addLayout(h_undo)
        
        # Separator
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.layout.addWidget(line)

        # --- 2. Main Editor ---
        lbl_desc = QLabel("Descriptions / Captions:")
        lbl_desc.setStyleSheet("font-weight: bold; font-size: 14px; color: #ddd;")
        self.layout.addWidget(lbl_desc)

        lbl_hint = QLabel("Modify the Q & A below freely.")
        lbl_hint.setStyleSheet("color: #888; font-size: 11px; font-style: italic;")
        self.layout.addWidget(lbl_hint)

        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Select an action to view Q&A...")
        self.caption_edit.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #f0f0f0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
                font-size: 13px;
                line-height: 1.5;
            }
        """)
        self.layout.addWidget(self.caption_edit, 1) 

        # --- 3. Action Buttons (Swapped Positions) ---
        h_btns = QHBoxLayout()
        h_btns.setSpacing(10)
        
        # Confirm Button (Now on LEFT) - Blue
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setMinimumHeight(40)
        self.confirm_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4; 
                color: white; 
                border-radius: 4px; 
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #0063b1;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
        """)
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)

        # Clear Button (Now on RIGHT) - Default
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.clicked.connect(self.clear_clicked.emit)

        h_btns.addWidget(self.confirm_btn)
        h_btns.addWidget(self.clear_btn)
        self.layout.addLayout(h_btns)