# __init__.py (in ui/localization/)

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QTabWidget
)
from PyQt6.QtCore import Qt, pyqtSignal

from .spotting_controls import AnnotationManagementWidget
from .annotation_table import AnnotationTableWidget
from .smart_spotting import SmartSpottingWidget

class LocalizationAnnotationPanel(QWidget):
    """
    Right Panel for Localization Mode.
    Contains: Undo/Redo Buttons (Global), and a TabWidget separating 
    Hand Annotation and Smart Annotation interfaces.
    """
    # Signal emitted when the user switches between Hand and Smart tabs
    # The Controller should catch this to swap the Timeline markers
    tabSwitched = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        # self.setFixedWidth(400) # REMOVED: To allow expansion in enlarged dock
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # --- 1. Header (Undo/Redo removed and moved to menu bar) ---
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 5)
        
        lbl = QLabel("Annotation Controls")
        lbl.setStyleSheet("font-weight: bold; color: #BBB; font-size: 13px;")
        
        header_layout.addWidget(lbl)
        header_layout.addStretch()
        layout.addLayout(header_layout)
        
        # --- 2. Main Tabs ---
        self.tabs = QTabWidget()
        self.tabs.setObjectName("localization_tabs")
        layout.addWidget(self.tabs)

        # ========== TAB 0: Hand Annotation ==========
        self.hand_widget = QWidget()
        hand_layout = QVBoxLayout(self.hand_widget)
        hand_layout.setContentsMargins(0, 5, 0, 0)
        
        # Top: Multi Head Management (Tabs for categories)
        self.annot_mgmt = AnnotationManagementWidget()
        # Bottom: Labelled Event List (Table for hand annotations)
        self.table = AnnotationTableWidget()
        
        hand_layout.addWidget(self.annot_mgmt, 2) 
        hand_layout.addWidget(self.table, 3)
        
        self.tabs.addTab(self.hand_widget, "Hand Annotation")

        # ========== TAB 1: Smart Annotation ==========
        # Loads the newly created SmartSpottingWidget
        self.smart_widget = SmartSpottingWidget()
        self.tabs.addTab(self.smart_widget, "Smart Annotation")

        # Connect tab change signal
        self.tabs.currentChanged.connect(self.tabSwitched.emit)