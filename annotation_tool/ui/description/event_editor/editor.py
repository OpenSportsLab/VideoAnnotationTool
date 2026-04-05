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
    confirm_clicked = pyqtSignal()      # Save changes
    clear_clicked = pyqtSignal()        # Clear text

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(350) 
        
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(10)
        self.layout.setContentsMargins(15, 15, 15, 15)
        
        # 1. Undo/Redo removed (moved to menu bar)
        
        # --- 2. Text Editor Area ---
        lbl_instr = QLabel("Description / Caption:")
        # You can also move this style to QSS if you want complete separation
        lbl_instr.setStyleSheet("font-weight: bold; color: #ccc;") 
        self.layout.addWidget(lbl_instr)
        
        self.caption_edit = QTextEdit()
        self.caption_edit.setPlaceholderText("Type description here...")
        
        # Style via QSS
        self.caption_edit.setObjectName("descCaptionEdit")
        
        self.layout.addWidget(self.caption_edit, 1) 

        # --- 3. Action Buttons ---
        h_btns = QHBoxLayout()
        h_btns.setSpacing(10)
        
        # Confirm Button (Blue)
        self.confirm_btn = QPushButton("Confirm")
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.setMinimumHeight(40)
        
        # Style via QSS
        self.confirm_btn.setObjectName("descConfirmBtn")
        self.confirm_btn.clicked.connect(self.confirm_clicked.emit)

        # Clear Button
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setMinimumHeight(40)
        
        # Style via QSS
        self.clear_btn.setObjectName("descClearBtn")
        self.clear_btn.clicked.connect(self.clear_clicked.emit)
        
        # [CHANGED] Swap Order: Clear (Left) -> Confirm (Right)
        # Stretch factors: Clear gets 1 share, Confirm gets 2 shares (wider)
        h_btns.addWidget(self.clear_btn, 1)   
        h_btns.addWidget(self.confirm_btn, 2) 
        
        self.layout.addLayout(h_btns)