from PyQt6.QtWidgets import QWidget, QHBoxLayout

# Import the common tree panel
from ui.common.clip_explorer import CommonProjectTreePanel

class UnifiedTaskPanel(QWidget):
    """
    A generic 3-column workspace container used for both Classification and Localization.
    
    Structure:
    [ Left: Project Tree ] -- [ Center: Player/Visualizer ] -- [ Right: Editor/Controls ]
    
    This unifies the layout logic so both modes look consistent.
    """
    def __init__(self, 
                 center_widget: QWidget, 
                 right_widget: QWidget, 
                 tree_title: str = "Clips / Sequences",
                 filter_items: list = None,
                 clear_text: str = "Clear All",
                 parent=None):
        """
        Args:
            center_widget: The widget to place in the center (expandable).
            right_widget: The widget to place on the right (fixed width usually).
            tree_title: Title for the left tree panel (e.g. 'Clips / Sequences').
            filter_items: Items for the filter dropdown.
            clear_text: Text for the clear button.
        """
        super().__init__(parent)
        
        # 1. Setup Layout
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        
        # 2. Instantiate Left Panel (Common)
        # Default to Localization-style naming if not provided
        if filter_items is None:
            filter_items = ["Show All", "Show Labelled", "No Labelled"]

        self.left_panel = CommonProjectTreePanel(
            tree_title=tree_title,
            filter_items=filter_items,
            clear_text=clear_text,
            enable_context_menu=True
        )
        
        # 3. Assign Center and Right Panels
        self.center_panel = center_widget
        self.right_panel = right_widget
        
        # 4. Add to Layout
        # Left panel is fixed width (handled inside CommonProjectTreePanel)
        layout.addWidget(self.left_panel)
        # Center panel gets stretch factor 1 (takes remaining space)
        layout.addWidget(self.center_panel, 1) 
        # Right panel is fixed width (handled inside specific right widgets)
        layout.addWidget(self.right_panel)