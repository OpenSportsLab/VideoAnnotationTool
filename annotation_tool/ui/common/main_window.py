from PyQt6.QtWidgets import QWidget, QVBoxLayout, QStackedLayout

# 1. Import common widgets
from ui.common.welcome_widget import WelcomeWidget
from ui.common.workspace import MainWorkspace

class MainWindowUI(QWidget):
    """
    The main container that switches between the Welcome screen and the 
    Unified Main Workspace.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.stack_layout = QStackedLayout()
        
        # --- View 0: Welcome Screen ---
        self.welcome_widget = WelcomeWidget()
        
        # --- View 1: Unified Main Workspace ---
        # "unique left panel, generic central widget, right panel with 4 tabs"
        self.workspace = MainWorkspace()
        
        # Add views to the Stack
        self.stack_layout.addWidget(self.welcome_widget) # Index 0
        self.stack_layout.addWidget(self.workspace)      # Index 1
        
        self.main_layout.addLayout(self.stack_layout)
        
        # Start at Welcome screen
        self.show_welcome_view()

    def show_welcome_view(self):
        """Switch to the Welcome Screen (Index 0)."""
        self.stack_layout.setCurrentIndex(0)

    def show_workspace(self):
        """Switch to the Main Workspace (Index 1)."""
        self.stack_layout.setCurrentIndex(1)

    # --- Mode-specific tab switching helpers ---
    # These helpers ensure the correct tab is selected in the Right Panel.

    def show_classification_view(self):
        self.show_workspace()
        self.workspace.right_tabs.setCurrentIndex(0)

    def show_localization_view(self):
        self.show_workspace()
        self.workspace.right_tabs.setCurrentIndex(1)

    def show_description_view(self):
        self.show_workspace()
        self.workspace.right_tabs.setCurrentIndex(2)

    def show_dense_description_view(self):
        self.show_workspace()
        self.workspace.right_tabs.setCurrentIndex(3)