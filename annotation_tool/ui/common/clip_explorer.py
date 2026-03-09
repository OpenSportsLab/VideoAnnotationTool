import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeView, # CHANGED: QTreeView instead of QTreeWidget
    QLabel, QComboBox, QPushButton, QMenu, QAbstractItemView
)
from PyQt6.QtCore import Qt, pyqtSignal, QModelIndex

# Import the shared controls
from ui.common.project_controls import UnifiedProjectControls

class CommonProjectTreePanel(QWidget):
    """
    A unified Left Panel for both Classification and Localization.
    Refactored to follow Model/View architecture using QTreeView.
    """
    
    # Signal emitted when "Remove Item" is clicked in context menu
    # Emits the QModelIndex of the item to be removed
    request_remove_item = pyqtSignal(QModelIndex)

    def __init__(self, 
                 tree_title="Project Items", 
                 filter_items=None, 
                 clear_text="Clear All", 
                 enable_context_menu=True,
                 parent=None):
        super().__init__(parent)
        self.setFixedWidth(250)
        
        # Main Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        
        # 1. Project Controls
        self.project_controls = UnifiedProjectControls()
        
        # Expose control buttons for external controller connections
        self.import_btn = self.project_controls.btn_load
        self.create_btn = self.project_controls.btn_create
        self.add_data_btn = self.project_controls.btn_add
        
        layout.addWidget(self.project_controls)
        
        # 2. Tree Title
        self.lbl_title = QLabel(tree_title)
        self.lbl_title.setProperty("class", "panel_header_lbl")
        layout.addWidget(self.lbl_title)
        
        # 3. The Tree View (MV Architecture)
        self.tree = QTreeView()
        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.tree)
        
        # Context Menu Logic
        if enable_context_menu:
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._show_context_menu)

        # 4. Filter & Clear Row
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(0, 5, 0, 0)
        
        self.lbl_filter = QLabel("Filter:")
        self.filter_combo = QComboBox()
        if filter_items:
            self.filter_combo.addItems(filter_items)
            
        self.clear_btn = QPushButton(clear_text)
        self.clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clear_btn.setObjectName("panel_clear_btn")
        
        bottom_layout.addWidget(self.lbl_filter)
        bottom_layout.addWidget(self.filter_combo, 1) # Stretch
        bottom_layout.addWidget(self.clear_btn)
        
        layout.addLayout(bottom_layout)

    def _show_context_menu(self, pos):
        """
        Handles the context menu request. Maps position to Model Index.
        """
        index = self.tree.indexAt(pos)
        if index.isValid():
            menu = QMenu()
            remove_action = menu.addAction("Remove Item")
            action = menu.exec(self.tree.mapToGlobal(pos))
            if action == remove_action:
                self.request_remove_item.emit(index)