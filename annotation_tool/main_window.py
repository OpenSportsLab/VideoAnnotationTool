import copy
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
            filter_items=["Show All", "Show Labelled", "Show Smart Labelled", "Show Not Labelled"],
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

        # --- Local UI state (icons, etc.) ---
        bright_blue = QColor("#00BFFF")
        self.done_icon = create_checkmark_icon(bright_blue)
        self.empty_icon = QIcon()

        # Dataset explorer now owns the canonical dataset document.
        self.dataset_explorer_controller = DatasetExplorerController(
            panel=self.dataset_explorer_panel,
            tree_model=self.tree_model,
        )
        self.dataset_explorer_controller.set_status_icons(self.done_icon, self.empty_icon)

        # --- Controllers ---
        self.classification_editor_controller = ClassificationEditorController(
            classification_panel=self.classification_panel,
        )
        self.localization_editor_controller = LocalizationEditorController(
            localization_panel=self.localization_panel,
        )

        # Description Mode Controller
        self.desc_editor_controller = DescEditorController(
            description_panel=self.description_panel,
        )

        # Dense Description Controller
        self.dense_editor_controller = DenseEditorController(
            dense_panel=self.dense_panel,
        )

        self.history_manager = HistoryManager(
            model=self.dataset_explorer_controller,
            tree_model=self.tree_model,
            current_tab_index_provider=self.right_tabs.currentIndex,
            current_action_path_provider=self.get_current_action_path,
            dense_current_video_path_provider=lambda: self.dense_editor_controller.current_video_path,
            current_filter_index_provider=self.dataset_explorer_panel.filter_combo.currentIndex,
        )
        self.welcome_controller = WelcomeController(self.welcome_widget, self.dataset_explorer_controller, self)

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
        self.reset_editor_panels()
        
        # Also clear the tree model
        self.tree_model.clear()
        self.dataset_explorer_controller.action_item_map.clear()
        self.main_window_title = "Action Classifier"
        self.setWindowTitle("Action Classifier")

        # Return to Welcome
        self.show_welcome_view()

    def reset_editor_panels(self):
        self.classification_editor_controller.reset_ui()
        self.localization_editor_controller.reset_ui()
        self.desc_editor_controller.reset_ui()
        self.dense_editor_controller.reset_ui()

    def set_project_ui_enabled(self, enabled: bool):
        """Enables/Disables all project-related docks and editors."""
        self.data_dock.setEnabled(enabled)
        self.editor_dock.setEnabled(enabled)
        
        # Also explicitly disable the sub-editors to be safe
        self._set_annotation_panels_enabled_for_selection(enabled)

    def _set_annotation_panels_enabled_for_selection(self, enabled: bool):
        self.classification_panel.manual_box.setEnabled(enabled)
        self.localization_panel.setEnabled(enabled)
        self.description_panel.setEnabled(enabled)
        self.dense_panel.setEnabled(enabled)

    def _set_side_docks_visible(self, visible: bool):
        """Show or hide side dock widgets (dataset explorer + annotation editor)."""
        self.data_dock.setVisible(visible)
        self.editor_dock.setVisible(visible)

    # Welcome screen
    def _safe_import_annotations(self): self.dataset_explorer_controller.import_annotations()
    def _safe_create_project(self): self.dataset_explorer_controller.create_new_project_flow()
    def _safe_close_dataset_or_quit(self):
        if self.dataset_explorer_controller.json_loaded:
            self.dataset_explorer_controller.close_project()
        else:
            self.close()

    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # --- COMPONENT REFS ---
        center_panel = self.center_panel

        # Runtime dataset context wiring for helper services.
        self.classification_editor_controller.inference_manager.set_dataset_model(self.dataset_explorer_controller)
        self.classification_editor_controller.train_manager.set_dataset_model(self.dataset_explorer_controller)
        
        # --- Dataset Explorer panel (Unified) ---
        # Handled by dataset_explorer_controller for clear PMC separation,
        # but the controller will internally call MainWindow dispatchers
        # when it needs global context.
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            lambda sample: self.classification_editor_controller.on_selected_sample_changed(
                sample,
                self.dataset_explorer_controller.get_path_by_id(
                    str(sample.get("id") or "")
                ) if isinstance(sample, dict) else "",
            )
        )
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            lambda sample: self.localization_editor_controller.on_selected_sample_changed(
                sample,
                self.dataset_explorer_controller.get_path_by_id(
                    str(sample.get("id") or "")
                ) if isinstance(sample, dict) else "",
            )
        )
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            self.desc_editor_controller.on_selected_sample_changed
        )
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            lambda sample: self.dense_editor_controller.on_selected_sample_changed(
                sample,
                self.dataset_explorer_controller.get_path_by_id(
                    str(sample.get("id") or "")
                ) if isinstance(sample, dict) else "",
            )
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.classification_editor_controller.on_schema_context_changed
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.localization_editor_controller.on_schema_context_changed
        )
        self.dataset_explorer_controller.mediaRouteRequested.connect(
            lambda path, ensure_playback: self.media_controller.route_media_selection(path, ensure_playback)
        )
        self.dataset_explorer_controller.mediaStopRequested.connect(lambda: self.media_controller.stop())
        self.dataset_explorer_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.dataset_explorer_controller.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.dataset_explorer_controller.schemaRefreshRequested.connect(self._refresh_schema_panels)
        self.dataset_explorer_controller.batchDropdownSyncRequested.connect(
            self.classification_editor_controller.sync_batch_inference_dropdowns
        )
        self.dataset_explorer_controller.classificationActionListChanged.connect(
            self.classification_editor_controller.on_action_items_changed
        )
        self.dataset_explorer_controller.classificationActionListChanged.connect(
            self.localization_editor_controller.on_action_items_changed
        )
        self.dataset_explorer_controller.workspaceViewRequested.connect(self.show_workspace)
        self.dataset_explorer_controller.welcomeViewRequested.connect(self.show_welcome_view)
        self.dataset_explorer_controller.resetEditorsRequested.connect(self.reset_editor_panels)
        self.dataset_explorer_controller.editorTabRequested.connect(self.right_tabs.setCurrentIndex)
        self.dataset_explorer_controller.descSaveRequested.connect(self.desc_editor_controller.save_current_annotation)
        self.dataset_explorer_controller.clearMarkersRequested.connect(lambda: self.center_panel.set_markers([]))
        self.dataset_explorer_controller.annotationPanelsEnabledRequested.connect(
            self._set_annotation_panels_enabled_for_selection
        )
        self.dataset_explorer_controller.headerDraftMutationRequested.connect(
            self.history_manager.execute_header_draft_update
        )
        self.dataset_explorer_controller.sampleRenameRequested.connect(
            self.history_manager.execute_sample_id_rename,
            Qt.ConnectionType.QueuedConnection,
        )
        self.dataset_explorer_controller.addSamplesRequested.connect(
            self.history_manager.execute_add_samples
        )
        self.dataset_explorer_controller.clearWorkspaceRequested.connect(
            self.history_manager.execute_clear_workspace
        )
        self.dataset_explorer_controller.removeItemMutationRequested.connect(
            self.history_manager.execute_remove_item
        )


        # --- Center panel (Unified Playback) ---
        center_panel.playPauseRequested.connect(self.media_controller.toggle_play_pause)
        center_panel.muteToggleRequested.connect(self.media_controller.toggle_mute)
        center_panel.seekRelativeRequested.connect(self.media_controller.seek_relative)
        center_panel.stopRequested.connect(lambda: self.media_controller.stop())
        center_panel.playbackRateRequested.connect(center_panel.set_playback_rate)
        self.media_controller.playbackStateChanged.connect(self.localization_editor_controller.on_playback_state_changed)
        center_panel.positionChanged.connect(self.localization_editor_controller.on_media_position_changed)
        center_panel.positionChanged.connect(self.dense_editor_controller.on_media_position_changed)
        self.media_controller.muteStateChanged.connect(center_panel.set_mute_button_state)
        center_panel.set_mute_button_state(self.media_controller.is_muted())
        # Dense add should always pause playback first; no auto-resume behavior.
        self.dense_panel.addEventRequested.connect(self.media_controller.pause)
        # Snapshot runtime media position on dense actions.
        self.dense_panel.addEventRequested.connect(
            lambda: self.dense_editor_controller.on_media_position_changed(self.center_panel.player.position())
        )
        self.dense_panel.updateTimeForSelectedRequested.connect(
            lambda _event: self.dense_editor_controller.on_media_position_changed(self.center_panel.player.position())
        )
        self.dense_panel.eventNavigateRequested.connect(
            lambda _step: self.dense_editor_controller.on_media_position_changed(self.center_panel.player.position())
        )

        # --- Controller shell update signals ---
        self.classification_editor_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.classification_editor_controller.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.classification_editor_controller.itemStatusRefreshRequested.connect(self.update_action_item_status)
        self.classification_editor_controller.manualAnnotationSaveRequested.connect(
            self.history_manager.execute_classification_manual_annotation
        )
        self.classification_editor_controller.schemaHeadAddRequested.connect(
            self.history_manager.execute_classification_schema_add_head
        )
        self.classification_editor_controller.schemaHeadRemoveRequested.connect(
            self.history_manager.execute_classification_schema_remove_head
        )
        self.classification_editor_controller.schemaLabelAddRequested.connect(
            self.history_manager.execute_classification_schema_add_label
        )
        self.classification_editor_controller.schemaLabelRemoveRequested.connect(
            self.history_manager.execute_classification_schema_remove_label
        )

        self.localization_editor_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.localization_editor_controller.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.localization_editor_controller.itemStatusRefreshRequested.connect(self.update_action_item_status)
        self.localization_editor_controller.mediaSeekRequested.connect(self.center_panel.set_position)
        self.localization_editor_controller.markersUpdateRequested.connect(self.center_panel.set_markers)
        self.localization_editor_controller.mediaTogglePlaybackRequested.connect(
            lambda: self.center_panel.playPauseRequested.emit()
        )
        self.localization_editor_controller.locHeadAddRequested.connect(
            self.history_manager.execute_localization_head_add
        )
        self.localization_editor_controller.locHeadRenameRequested.connect(
            self.history_manager.execute_localization_head_rename
        )
        self.localization_editor_controller.locHeadDeleteRequested.connect(
            self.history_manager.execute_localization_head_delete
        )
        self.localization_editor_controller.locLabelAddRequested.connect(
            self.history_manager.execute_localization_label_add
        )
        self.localization_editor_controller.locLabelRenameRequested.connect(
            self.history_manager.execute_localization_label_rename
        )
        self.localization_editor_controller.locLabelDeleteRequested.connect(
            self.history_manager.execute_localization_label_delete
        )
        self.localization_editor_controller.locEventAddRequested.connect(
            self.history_manager.execute_localization_event_add
        )
        self.localization_editor_controller.locEventModRequested.connect(
            self.history_manager.execute_localization_event_mod
        )
        self.localization_editor_controller.locEventDelRequested.connect(
            self.history_manager.execute_localization_event_delete
        )
        self.localization_editor_controller.locSmartEventsSetRequested.connect(
            self.history_manager.execute_localization_smart_events_set
        )
        self.localization_editor_controller.locSmartEventsConfirmRequested.connect(
            self.history_manager.execute_localization_smart_events_confirm
        )
        self.localization_editor_controller.locSmartEventsClearRequested.connect(
            self.history_manager.execute_localization_smart_events_clear
        )

        self.desc_editor_controller.clearMarkersRequested.connect(lambda: self.center_panel.set_markers([]))
        self.desc_editor_controller.captionsUpdateRequested.connect(
            self.history_manager.execute_sample_captions_update
        )

        self.dense_editor_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.dense_editor_controller.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.dense_editor_controller.itemStatusRefreshRequested.connect(self.update_action_item_status)
        self.dense_editor_controller.denseEventAddRequested.connect(
            self.history_manager.execute_dense_event_add
        )
        self.dense_editor_controller.denseEventModRequested.connect(
            self.history_manager.execute_dense_event_mod
        )
        self.dense_editor_controller.denseEventDelRequested.connect(
            self.history_manager.execute_dense_event_del
        )
        self.dense_editor_controller.mediaSeekRequested.connect(self.center_panel.set_position)
        self.dense_editor_controller.markersUpdateRequested.connect(self.center_panel.set_markers)

        # --- History manager request signals ---
        self.history_manager.allItemStatusRefreshRequested.connect(self.dataset_explorer_controller.refresh_all_item_statuses)
        self.history_manager.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.history_manager.statusMessageRequested.connect(self.show_temp_msg)
        self.history_manager.filterRefreshRequested.connect(self.dataset_explorer_controller.handle_filter_change)
        self.history_manager.refreshUiAfterUndoRedoRequested.connect(self.refresh_ui_after_undo_redo)
        self.history_manager.classificationSetupRequested.connect(
            self._refresh_classification_schema_context
        )
        self.history_manager.localizationSchemaRefreshRequested.connect(
            self._refresh_localization_schema_context
        )
        self.history_manager.localizationClipEventsRefreshRequested.connect(
            self.localization_editor_controller._refresh_current_clip_events
        )
        self.history_manager.denseDisplayRequested.connect(self.dense_editor_controller.display_events_for_item)
        self.history_manager.itemStatusRefreshRequested.connect(self.update_action_item_status)
        self.history_manager.datasetRestoreRequested.connect(self.dataset_explorer_controller.restore_dataset_json_from_history)

        # --- Mode change fanout ---
        self.right_tabs.currentChanged.connect(self.dataset_explorer_controller.set_active_mode)
        self.right_tabs.currentChanged.connect(self.dataset_explorer_controller.handle_active_mode_changed)
        self.right_tabs.currentChanged.connect(self.classification_editor_controller.on_mode_changed)
        self.right_tabs.currentChanged.connect(self.localization_editor_controller.on_mode_changed)
        self.right_tabs.currentChanged.connect(self.desc_editor_controller.on_mode_changed)
        self.right_tabs.currentChanged.connect(self.dense_editor_controller.on_mode_changed)

        # --- Controllers' internal panel wiring ---
        self.classification_editor_controller.setup_connections()
        self.localization_editor_controller.setup_connections()
        self.desc_editor_controller.setup_connections()
        self.dense_editor_controller.setup_connections()

        current_mode = self.right_tabs.currentIndex()
        self.dataset_explorer_controller.set_active_mode(current_mode)
        self.classification_editor_controller.on_mode_changed(current_mode)
        self.localization_editor_controller.on_mode_changed(current_mode)
        self.desc_editor_controller.on_mode_changed(current_mode)
        self.dense_editor_controller.on_mode_changed(current_mode)

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

    def _refresh_schema_panels(self):
        self._refresh_classification_schema_context()
        self._refresh_localization_schema_context()

    def _refresh_classification_schema_context(self):
        self.classification_editor_controller.on_schema_context_changed(
            copy.deepcopy(self.dataset_explorer_controller.label_definitions)
        )

    def _refresh_localization_schema_context(self):
        self.localization_editor_controller.on_schema_context_changed(
            copy.deepcopy(self.dataset_explorer_controller.label_definitions)
        )

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
        has_data = self.dataset_explorer_controller.json_loaded # Simple heuristic for now
        can_export = self.dataset_explorer_controller.json_loaded
        can_save = (
            can_export
            and (self.dataset_explorer_controller.current_json_path is not None)
            and self.dataset_explorer_controller.is_data_dirty
        )
        self.action_save.setEnabled(can_save)
        self.action_export.setEnabled(can_export)
        self.action_undo.setEnabled(len(self.dataset_explorer_controller.undo_stack) > 0)
        self.action_redo.setEnabled(len(self.dataset_explorer_controller.redo_stack) > 0)
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
        self.dataset_explorer_controller.handle_filter_change(
            self.dataset_explorer_panel.filter_combo.currentIndex()
        )

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
            item = self.dataset_explorer_controller.action_item_map.get(action_path)
            if item:
                idx = item.index()
                if idx.isValid() and not self.dataset_explorer_panel.tree.isRowHidden(idx.row(), QModelIndex()):
                    if self.dataset_explorer_panel.tree.currentIndex() != idx:
                        self.dataset_explorer_panel.tree.setCurrentIndex(idx)

        self.dataset_explorer_controller.reemit_current_selection()

        self.update_save_export_button_state()
