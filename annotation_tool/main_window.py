import os

from PyQt6.QtCore import Qt, QModelIndex
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QDockWidget, QMainWindow, QStackedWidget, QTabWidget

from controllers.classification import ClassificationEditorController
from controllers.localization import LocalizationEditorController
from controllers.description import DescEditorController
from controllers.dense_description import DenseEditorController
from controllers.history_manager import HistoryManager
from controllers.media_controller import MediaController
from controllers.dataset_explorer_controller import DatasetExplorerController
from controllers.welcome_controller import WelcomeController

# [NEW] Direct UI Imports
from ui.welcome_widget import WelcomeWidget
from ui.dataset_explorer_panel import DatasetExplorerPanel
from ui.media_player import MediaCenterPanel
from ui.classification import ClassificationAnnotationPanel
from ui.localization import LocalizationAnnotationPanel
from ui.description import DescriptionAnnotationPanel
from ui.dense_description import DenseAnnotationPanel

from utils import create_checkmark_icon, resource_path


class VideoAnnotationWindow(QMainWindow):
    """
    Main application window for annotation + localization + description + dense workflows.
    Now directly implements the UI setup to avoid overcomplicated nesting.
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Video Annotation Tool")
        self.resize(1200, 800)

        # --- 1. Center Area: Stacked Widget (Welcome vs Media Player) ---
        self.center_stack = QStackedWidget()
        
        self.welcome_widget = WelcomeWidget()
        self.center_stack.addWidget(self.welcome_widget)
        
        self.center_panel = MediaCenterPanel()
        self.center_stack.addWidget(self.center_panel)
        
        self.setCentralWidget(self.center_stack)

        # --- 2. Left Dock: Dataset Explorer ---
        self.dataset_explorer_panel = DatasetExplorerPanel(
            tree_title="Data",
            filter_items=["Show All", "Show Hand Labelled", "Show Smart Labelled", "Show Not Labelled"],
            clear_text="Clear All",
            enable_context_menu=True
        )
        self.tree_model = self.dataset_explorer_panel.tree_model
        
        self.data_dock = QDockWidget("Dataset Explorer", self)
        self.data_dock.setObjectName("DatasetExplorerDock")
        self.data_dock.setWidget(self.dataset_explorer_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.data_dock)

        # --- 3. Right Dock: Annotation Editors ---
        self.right_tabs = QTabWidget()
        self.right_tabs.setDocumentMode(True)
        
        self.classification_panel = ClassificationAnnotationPanel()
        self.localization_panel = LocalizationAnnotationPanel()
        self.description_panel = DescriptionAnnotationPanel()
        self.dense_panel = DenseAnnotationPanel()
        
        self.right_tabs.addTab(self.classification_panel, "CLS")
        self.right_tabs.addTab(self.localization_panel, "LOC")
        self.right_tabs.addTab(self.description_panel, "DESC")
        self.right_tabs.addTab(self.dense_panel, "DENSE")
        
        self.editor_dock = QDockWidget("Annotation Editor", self)
        self.editor_dock.setObjectName("AnnotationEditorDock")
        self.editor_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.editor_dock)
        self.editor_dock.setMinimumWidth(300)

        # Start with a slimmer right editor dock so media gets more horizontal space.
        self.resizeDocks(
            [self.data_dock, self.editor_dock],
            [100, 100],
            Qt.Orientation.Horizontal,
        )

        # Allow nested docking and tabbed docks
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AnimatedDocks)

        # Central playback controller.
        self.media_controller = MediaController(self.center_panel.player, self.center_panel.video_widget)

        # Dataset explorer now owns the canonical dataset document.
        self.dataset_explorer_controller = DatasetExplorerController(
            main_window=self,
            panel=self.dataset_explorer_panel,
            tree_model=self.tree_model,
            media_controller=self.media_controller,
        )
        self.model = self.dataset_explorer_controller
        self.router = self.dataset_explorer_controller

        # --- Controllers ---
        self.welcome_controller = WelcomeController(self.welcome_widget, self.router, self)
        self.history_manager = HistoryManager(self)

        self.classification_editor_controller = ClassificationEditorController(
            self, self.media_controller
        )
        self.localization_editor_controller = LocalizationEditorController(self, self.media_controller)
        
        # Description Mode Controller
        self.desc_editor_controller = DescEditorController(self)
        
        # Dense Description Controller
        self.dense_editor_controller = DenseEditorController(self, self.media_controller)
        # --- Local UI state (icons, etc.) ---
        bright_blue = QColor("#00BFFF")
        self.done_icon = create_checkmark_icon(bright_blue)
        self.empty_icon = QIcon()

        # --- Setup ---
        self.connect_signals()
        self.load_stylesheet()
        
        self.classification_editor_controller.setup_dynamic_ui()
        self._setup_menu_bar()
        self._setup_shortcuts()

        # Start at welcome screen
        self.show_welcome_view()

    # ---------------------------------------------------------------------
    # View Switching Helpers (merged from MainWindowUI)
    # ---------------------------------------------------------------------
    def show_welcome_view(self):
        """Switch to the Welcome Screen (Index 0 in central stack)."""
        self.center_stack.setCurrentIndex(0)
        self.set_project_ui_enabled(False)
        self._set_side_docks_visible(False)
        if hasattr(self, "welcome_controller"):
            self.welcome_controller.refresh_recent_projects()

    def show_workspace(self):
        """Switch to the Media Player (Index 1 in central stack)."""
        self.center_stack.setCurrentIndex(1)
        self._set_side_docks_visible(True)
        self.set_project_ui_enabled(True)

    def show_classification_view(self):
        self.show_workspace()
        self.right_tabs.setCurrentIndex(0)

    def show_localization_view(self):
        self.show_workspace()
        self.right_tabs.setCurrentIndex(1)

    def show_description_view(self):
        self.show_workspace()
        self.right_tabs.setCurrentIndex(2)

    def show_dense_description_view(self):
        self.show_workspace()
        self.right_tabs.setCurrentIndex(3)

    def reset_all_managers(self):
        """ Clears all mode-specific UIs and returns to Welcome screen. """
        self.classification_editor_controller.reset_ui()
        self.localization_editor_controller.reset_ui()
        self.desc_editor_controller.reset_ui()
        self.dense_editor_controller.reset_ui()
        
        # Also clear the tree model
        self.tree_model.clear()
        self.model.action_item_map.clear()
        self.main_window_title = "Action Classifier"
        self.setWindowTitle("Action Classifier")

        # Return to Welcome
        self.show_welcome_view()

    def set_project_ui_enabled(self, enabled: bool):
        """Enables/Disables all project-related docks and editors."""
        self.data_dock.setEnabled(enabled)
        self.editor_dock.setEnabled(enabled)
        
        # Also explicitly disable the sub-editors to be safe
        self.classification_panel.manual_box.setEnabled(enabled)
        self.localization_panel.setEnabled(enabled)
        self.description_panel.setEnabled(enabled)
        self.dense_panel.setEnabled(enabled)

    def _set_side_docks_visible(self, visible: bool):
        """Show or hide side dock widgets (dataset explorer + annotation editor)."""
        self.data_dock.setVisible(visible)
        self.editor_dock.setVisible(visible)

    # Welcome screen
    def _safe_import_annotations(self): self.router.import_annotations()
    def _safe_create_project(self): self.router.create_new_project_flow()
    def _safe_close_dataset_or_quit(self):
        if self.model.json_loaded:
            self.dataset_explorer_controller.close_project()
        else:
            self.close()

    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # --- COMPONENT REFS ---
        center_panel = self.center_panel
        
        # --- Dataset Explorer panel (Unified) ---
        # Handled by dataset_explorer_controller for clear PMC separation,
        # but the controller will internally call MainWindow dispatchers
        # when it needs global context.
        self.dataset_explorer_controller.dataSelected.connect(self.classification_editor_controller.on_data_selected)
        self.dataset_explorer_controller.dataSelected.connect(self.localization_editor_controller.on_data_selected)
        self.dataset_explorer_controller.dataSelected.connect(self.desc_editor_controller.on_data_selected)
        self.dataset_explorer_controller.dataSelected.connect(self.dense_editor_controller.on_data_selected)
        self.right_tabs.currentChanged.connect(self._on_editor_tab_changed)


        # --- Center panel (Unified Playback) ---
        center_panel.playPauseRequested.connect(self.media_controller.toggle_play_pause)
        center_panel.seekRelativeRequested.connect(self.media_controller.seek_relative)
        center_panel.stopRequested.connect(self.media_controller.stop)
        center_panel.playbackRateRequested.connect(center_panel.set_playback_rate)
        
        # --- Classification Editor ---
        self.classification_editor_controller.setup_connections()

        # --- Localization Editor ---
        self.localization_editor_controller.setup_connections()

        # --- Description Editor ---
        self.desc_editor_controller.setup_connections()

        # --- Dense Editor ---
        self.dense_editor_controller.setup_connections()

    def _setup_menu_bar(self) -> None:
        from PyQt6.QtGui import QAction
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        self.action_create = QAction("Create New Dataset", self)
        self.action_create.triggered.connect(self._safe_create_project)
        file_menu.addAction(self.action_create)

        self.action_load = QAction("Load Dataset", self)
        self.action_load.triggered.connect(self._safe_import_annotations)
        file_menu.addAction(self.action_load)

        self.action_close = QAction("Close Dataset", self)
        self.action_close.triggered.connect(self.dataset_explorer_controller.close_project)
        file_menu.addAction(self.action_close)

        file_menu.addSeparator()

        self.action_save = QAction("Save Dataset", self)
        self.action_save.triggered.connect(self.dataset_explorer_controller.save_project)
        self.action_save.setEnabled(False)
        file_menu.addAction(self.action_save)

        self.action_export = QAction("Save Dataset As", self)
        self.action_export.triggered.connect(self.dataset_explorer_controller.export_project)
        self.action_export.setEnabled(False)
        file_menu.addAction(self.action_export)

        file_menu.addSeparator()

        self.action_quit = QAction("Quit", self)
        self.action_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.action_quit.setMenuRole(QAction.MenuRole.QuitRole)
        self.action_quit.triggered.connect(self._safe_close_dataset_or_quit)
        file_menu.addAction(self.action_quit)

        edit_menu = menu_bar.addMenu("&Edit")
        self.action_undo = QAction("Undo", self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self.history_manager.perform_undo)
        edit_menu.addAction(self.action_undo)
        
        self.action_redo = QAction("Redo", self)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self.history_manager.perform_redo)
        edit_menu.addAction(self.action_redo)

    def _setup_shortcuts(self) -> None:
        """Register common keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._safe_import_annotations)
        
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.dataset_explorer_controller.save_project)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(
            self.dataset_explorer_controller.export_project
        )

        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(
            lambda: self.show_temp_msg("Settings", "Settings dialog not implemented yet.")
        )
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(
            lambda: self.show_temp_msg("Downloader", "Dataset downloader not implemented yet.")
        )

        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self.history_manager.perform_undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self.history_manager.perform_redo)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(
            self.media_controller.toggle_play_pause
        )
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(
            lambda: self.media_controller.seek_relative(-40)
        )
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(
            lambda: self.media_controller.seek_relative(40)
        )
        QShortcut(QKeySequence("Ctrl+Left"), self).activated.connect(
            lambda: self.media_controller.seek_relative(-1000)
        )
        QShortcut(QKeySequence("Ctrl+Right"), self).activated.connect(
            lambda: self.media_controller.seek_relative(1000)
        )
        QShortcut(QKeySequence("Ctrl+Shift+Left"), self).activated.connect(
            lambda: self.media_controller.seek_relative(-5000)
        )
        QShortcut(QKeySequence("Ctrl+Shift+Right"), self).activated.connect(
            lambda: self.media_controller.seek_relative(5000)
        )

        QShortcut(QKeySequence("S"), self).activated.connect(
            lambda: self.show_temp_msg("Info", "Select an event and edit time via right-click.")
        )

    # # ---------------------------------------------------------------------
    # # Mode-aware dispatchers (Deprecated?)
    # # ---------------------------------------------------------------------
    # def _get_active_mode_index(self) -> int:
    #     return self.right_tabs.currentIndex()

    # def _is_cls_mode(self) -> bool: return self._get_active_mode_index() == 0
    # def _is_loc_mode(self) -> bool: return self._get_active_mode_index() == 1
    # def _is_desc_mode(self) -> bool: return self._get_active_mode_index() == 2
    # def _is_dense_mode(self) -> bool: return self._get_active_mode_index() == 3

    # def _on_remove_item_requested(self, index: QModelIndex):
    #     self.dataset_explorer_controller.handle_remove_item(index)

    # ---------------------------------------------------------------------
    # UI Helpers
    # ---------------------------------------------------------------------
    # def prepare_new_project_ui(self) -> None:
    #     self.set_project_ui_enabled(True)
    #     self.classification_editor_controller.setup_dynamic_ui()
    #     self.show_temp_msg("New Project Created", "Dataset ready.")

    # def prepare_new_localization_ui(self) -> None:
    #     self.prepare_new_project_ui()

    # def prepare_new_description_ui(self) -> None:
    #     self.prepare_new_project_ui()
    
    # def prepare_new_dense_ui(self) -> None:
    #     self.prepare_new_project_ui()

    def _on_editor_tab_changed(self, _index: int) -> None:
        self.dataset_explorer_controller.handle_active_mode_changed()

    def load_stylesheet(self) -> None:
        style_path = resource_path(os.path.join("style", "style.qss"))
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception as exc: print(f"Style error: {exc}")

    def check_and_close_current_project(self) -> bool:
        return self.dataset_explorer_controller.check_and_close_current_project()

    def closeEvent(self, event) -> None:
        if self.dataset_explorer_controller.check_and_close_current_project():
            self.media_controller.stop()
            event.accept()
        else:
            event.ignore()

    def update_save_export_button_state(self) -> None:
        has_data = self.model.json_loaded # Simple heuristic for now
        can_export = self.model.json_loaded
        can_save = can_export and (self.model.current_json_path is not None) and self.model.is_data_dirty
        self.action_save.setEnabled(can_save)
        self.action_export.setEnabled(can_export)
        self.action_undo.setEnabled(len(self.model.undo_stack) > 0)
        self.action_redo.setEnabled(len(self.model.redo_stack) > 0)
        if hasattr(self, "dataset_explorer_controller"):
            self.dataset_explorer_controller._refresh_json_preview()

    def show_temp_msg(self, title: str, msg: str, duration: int = 1500, **kwargs) -> None:
        one_line = " ".join(str(msg).splitlines()).strip()
        self.statusBar().showMessage(f"{title} — {one_line}" if title else one_line, duration)

    def get_current_action_path(self):
        tree_view = self.dataset_explorer_panel.tree
        idx = tree_view.selectionModel().currentIndex()
        if not idx.isValid(): return None
        if idx.parent().isValid(): return idx.parent().data(self.tree_model.FilePathRole)
        return idx.data(self.tree_model.FilePathRole)

    def sync_batch_inference_dropdowns(self) -> None:
        self.classification_editor_controller.sync_batch_inference_dropdowns()

    def populate_action_tree(self) -> None:
        """Loads data from the app state into the UI model tree."""
        self.dataset_explorer_controller.populate_tree()

    def update_action_item_status(self, action_path: str) -> None:
        """Updates the icon state for an item (Done/Not Done check)."""
        self.dataset_explorer_controller.update_item_status(action_path)

    def setup_dynamic_ui(self) -> None:
        self.classification_editor_controller.setup_dynamic_ui()

    def _connect_dynamic_type_buttons(self) -> None:
        self.classification_editor_controller._connect_dynamic_type_buttons()

    def refresh_ui_after_undo_redo(self, action_path: str, filter_selection_fallback: str = "first_visible") -> None:
        self.dataset_explorer_controller.refresh_all_item_statuses()
        self.dataset_explorer_controller.handle_filter_change(
            self.dataset_explorer_panel.filter_combo.currentIndex(),
            selection_fallback=filter_selection_fallback,
        )

        if action_path:
            item = self.model.action_item_map.get(action_path)
            if item:
                idx = item.index()
                if idx.isValid() and not self.dataset_explorer_panel.tree.isRowHidden(idx.row(), QModelIndex()):
                    if self.dataset_explorer_panel.tree.currentIndex() != idx:
                        self.dataset_explorer_panel.tree.setCurrentIndex(idx)

        selected_path = self.get_current_action_path()
        selected_data_id = self.model.get_data_id_by_path(selected_path) if selected_path else None
        if selected_data_id:
            self.dataset_explorer_controller.dataSelected.emit(selected_data_id)

        self.update_save_export_button_state()
