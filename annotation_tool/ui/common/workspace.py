from PyQt6.QtWidgets import QWidget, QHBoxLayout, QTabWidget, QMainWindow, QDockWidget
from PyQt6.QtCore import Qt

# Import common components
from ui.common.clip_explorer import CommonProjectTreePanel
from ui.localization.media_player import LocCenterPanel

# Import editors for the tabs
from ui.classification.event_editor import ClassificationEventEditor
from ui.localization.event_editor import LocRightPanel
from ui.description.event_editor import DescriptionEventEditor
from ui.dense_description.event_editor import DenseRightPanel

class MainWorkspace(QMainWindow):
    """
    A unified workspace containing a single data tree, a generic media player,
    and a tabbed right panel for different annotation modes.
    Now implemented using QDockWidgets for maximum flexibility.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 1. Center Panel: Generic Media Player
        # "generic central widget that shows me the player with all the playback control"
        self.center_panel = LocCenterPanel()
        self.setCentralWidget(self.center_panel)
        
        # 2. Left Dock: Unique Data List
        self.left_panel = CommonProjectTreePanel(
            tree_title="Data",
            filter_items=["Show All", "Hand Labelled", "Smart Labelled", "No Labelled"],
            clear_text="Clear All",
            enable_context_menu=True
        )
        self.data_dock = QDockWidget("Project Navigator", self)
        self.data_dock.setObjectName("DataNavigatorDock")
        self.data_dock.setWidget(self.left_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.data_dock)
        
        # 3. Right Dock: Tabbed Editors
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True) # Cleaner look for docks
        self.right_tabs.setTabPosition(QTabWidget.TabPosition.North) # Default top
        
        self.classification_editor = ClassificationEventEditor()
        self.localization_editor = LocRightPanel()
        self.description_editor = DescriptionEventEditor()
        self.dense_editor = DenseRightPanel()
        
        self.right_tabs.addTab(self.classification_editor, "CLS")
        self.right_tabs.addTab(self.localization_editor, "LOC")
        self.right_tabs.addTab(self.description_editor, "DESC")
        self.right_tabs.addTab(self.dense_editor, "DENSE")
        
        self.editor_dock = QDockWidget("Annotation Editor", self)
        self.editor_dock.setObjectName("AnnotationEditorDock")
        self.editor_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.editor_dock)
        
        # Allow nested docking and tabbed docks
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AnimatedDocks)
