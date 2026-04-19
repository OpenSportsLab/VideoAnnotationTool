import copy
import html
import os

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QLabel, QDockWidget, QMainWindow, QMessageBox, QStackedWidget, QTabWidget

from controllers.classification import ClassificationEditorController
from controllers.hf_transfer_controller import HfTransferController
from controllers.hf_transfer_service import (
    create_dataset_branch_on_hf,
    create_dataset_repo_on_hf,
    dataset_repo_exists_on_hf,
    is_hf_download_url_not_found_error,
    is_hf_repo_not_found_error,
    is_hf_revision_not_found_error,
    read_hf_source_metadata_from_dataset,
)
from controllers.localization import LocalizationEditorController
from controllers.description import DescEditorController
from controllers.dense_description import DenseEditorController
from controllers.question_answer import QAEditorController
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
from ui.question_answer import QuestionAnswerAnnotationPanel
from ui.dialogs import BusyStatusDialog, HfDownloadDialog, HfUploadDialog

from utils import create_checkmark_icon, resource_path


class VideoAnnotationWindow(QMainWindow):
    """
    Main application window for annotation + localization + description + dense + Q/A workflows.
    Now directly implements the UI setup to avoid overcomplicated nesting.
    """
    _MUTE_SETTING_KEY = "media/muted"

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
        self.qa_panel = QuestionAnswerAnnotationPanel()
        
        self.right_tabs.addTab(self.classification_panel, "CLS")
        self.right_tabs.addTab(self.localization_panel, "LOC")
        self.right_tabs.addTab(self.description_panel, "DESC")
        self.right_tabs.addTab(self.dense_panel, "DENSE")
        self.right_tabs.addTab(self.qa_panel, "Q/A")
        
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
        self.qa_editor_controller = QAEditorController(
            question_answer_panel=self.qa_panel,
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
        self.hf_transfer_controller = HfTransferController()
        self._hf_busy_dialog = None
        self._active_hf_transfer_kind: str | None = None
        self._last_hf_download_payload: dict | None = None
        self._last_hf_upload_payload: dict | None = None
        self._last_restored_mute_state: bool | None = None

        # Coalesce repeated status-triggered filter refreshes to avoid UI stalls
        # during rapid annotation mutations.
        self._status_filter_refresh_timer = QTimer(self)
        self._status_filter_refresh_timer.setSingleShot(True)
        self._status_filter_refresh_timer.setInterval(3000)
        self._status_filter_refresh_timer.timeout.connect(self._refresh_filter_after_status_update)

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

    def show_question_answer_view(self):
        self.show_workspace()
        self.right_tabs.setCurrentIndex(4)

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
        self.qa_editor_controller.reset_ui()

    def set_project_ui_enabled(self, enabled: bool):
        """Enables/Disables all project-related docks and editors."""
        self.data_dock.setEnabled(enabled)
        self.editor_dock.setEnabled(enabled)
        self.qa_editor_controller.set_question_bank_enabled(enabled)
        
        # Also explicitly disable the sub-editors to be safe
        self._set_annotation_panels_enabled_for_selection(enabled)

    def _set_annotation_panels_enabled_for_selection(self, enabled: bool):
        self.classification_panel.manual_box.setEnabled(enabled)
        self.localization_panel.setEnabled(enabled)
        self.description_panel.setEnabled(enabled)
        self.dense_panel.setEnabled(enabled)
        self.qa_editor_controller.set_sample_selection_enabled(enabled)

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
            self.classification_editor_controller.on_selected_sample_changed
        )
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            self.localization_editor_controller.on_selected_sample_changed
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
        self.dataset_explorer_controller.sampleSelectionChanged.connect(
            self.qa_editor_controller.on_selected_sample_changed
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.classification_editor_controller.on_schema_context_changed
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.localization_editor_controller.on_schema_context_changed
        )
        self.dataset_explorer_controller.questionBankChanged.connect(
            self.qa_editor_controller.on_question_bank_changed
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
        self.dataset_explorer_controller.qaSaveRequested.connect(self.qa_editor_controller.save_current_answers)
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
        self.dataset_explorer_controller.settingsChanged.connect(
            lambda _settings: self._restore_mute_state_from_settings()
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            self.localization_editor_controller.set_settings
        )
        self.localization_editor_controller.set_settings(self.dataset_explorer_controller.settings)


        # --- Center panel (Unified Playback) ---
        center_panel.playPauseRequested.connect(self.media_controller.toggle_play_pause)
        center_panel.muteToggleRequested.connect(self.media_controller.toggle_mute)
        center_panel.seekRelativeRequested.connect(self.media_controller.seek_relative)
        center_panel.stopRequested.connect(lambda: self.media_controller.stop())
        center_panel.playbackRateRequested.connect(center_panel.set_playback_rate)
        self.media_controller.playbackStateChanged.connect(self.localization_editor_controller.on_playback_state_changed)
        center_panel.positionChanged.connect(self.localization_editor_controller.on_media_position_changed)
        center_panel.durationChanged.connect(self.localization_editor_controller.on_media_duration_changed)
        center_panel.positionChanged.connect(self.dense_editor_controller.on_media_position_changed)
        self.media_controller.muteStateChanged.connect(center_panel.set_mute_button_state)
        self.media_controller.muteStateChanged.connect(self._save_mute_state_to_settings)
        center_panel.set_mute_button_state(self.media_controller.is_muted())
        self._restore_mute_state_from_settings()
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
        self.classification_editor_controller.schemaHeadRenameRequested.connect(
            self.history_manager.execute_classification_schema_rename_head
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
        self.localization_editor_controller.locLabelColorSetRequested.connect(
            self.history_manager.execute_localization_label_color_set
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
        self.localization_editor_controller.locEventsSetRequested.connect(
            self.history_manager.execute_localization_events_set
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

        self.qa_editor_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.qa_editor_controller.qaQuestionAddRequested.connect(
            self.history_manager.execute_qa_question_add
        )
        self.qa_editor_controller.qaQuestionRenameRequested.connect(
            self.history_manager.execute_qa_question_rename
        )
        self.qa_editor_controller.qaQuestionDeleteRequested.connect(
            self.history_manager.execute_qa_question_delete
        )
        self.qa_editor_controller.qaAnswersUpdateRequested.connect(
            self.history_manager.execute_qa_answers_update
        )

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
        self.history_manager.questionBankRefreshRequested.connect(
            self.dataset_explorer_controller._emit_question_bank_context
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
        self.right_tabs.currentChanged.connect(self.qa_editor_controller.on_mode_changed)

        # --- Controllers' internal panel wiring ---
        self.classification_editor_controller.setup_connections()
        self.localization_editor_controller.setup_connections()
        self.desc_editor_controller.setup_connections()
        self.dense_editor_controller.setup_connections()
        self.qa_editor_controller.setup_connections()

        current_mode = self.right_tabs.currentIndex()
        self.dataset_explorer_controller.set_active_mode(current_mode)
        self.classification_editor_controller.on_mode_changed(current_mode)
        self.localization_editor_controller.on_mode_changed(current_mode)
        self.desc_editor_controller.on_mode_changed(current_mode)
        self.dense_editor_controller.on_mode_changed(current_mode)
        self.qa_editor_controller.on_mode_changed(current_mode)

        # --- Hugging Face transfer wiring ---
        self.hf_transfer_controller.downloadStarted.connect(
            lambda message: self._on_hf_transfer_started("HF Download", message, "download")
        )
        self.hf_transfer_controller.downloadProgress.connect(
            lambda message: self._on_hf_transfer_progress("HF Download", message)
        )
        self.hf_transfer_controller.downloadCompleted.connect(self._on_hf_download_completed)
        self.hf_transfer_controller.downloadFailed.connect(self._on_hf_download_failed)
        self.hf_transfer_controller.downloadCancelled.connect(self._on_hf_download_cancelled)

        self.hf_transfer_controller.uploadStarted.connect(
            lambda message: self._on_hf_transfer_started("HF Upload", message, "upload")
        )
        self.hf_transfer_controller.uploadProgress.connect(
            lambda message: self._on_hf_transfer_progress("HF Upload", message)
        )
        self.hf_transfer_controller.uploadCompleted.connect(self._on_hf_upload_completed)
        self.hf_transfer_controller.uploadFailed.connect(self._on_hf_upload_failed)
        self.hf_transfer_controller.uploadCancelled.connect(self._on_hf_upload_cancelled)

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

        data_menu = menu_bar.addMenu("&Data")

        self.action_hf_download = QAction("Download Dataset from HF...", self)
        self.action_hf_download.triggered.connect(self._open_hf_download_dialog)
        data_menu.addAction(self.action_hf_download)

        self.action_hf_upload = QAction("Upload Dataset to HF...", self)
        self.action_hf_upload.triggered.connect(self._open_hf_upload_dialog)
        self.action_hf_upload.setEnabled(False)
        data_menu.addAction(self.action_hf_upload)

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
            self._open_hf_download_dialog
        )
        QShortcut(QKeySequence("Ctrl+U"), self).activated.connect(
            self._open_hf_upload_dialog
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
            if not self.classification_editor_controller.shutdown_background_tasks(wait_ms=2500):
                self.show_temp_msg(
                    "Inference Running",
                    "Classification inference is still running. Please wait and close again.",
                    2500,
                )
                event.ignore()
                return
            if not self.localization_editor_controller.shutdown_background_tasks(wait_ms=2500):
                self.show_temp_msg(
                    "Inference Running",
                    "Localization inference is still running. Please wait and close again.",
                    2500,
                )
                event.ignore()
                return
            self._close_hf_busy_dialog()
            self.media_controller.stop()
            event.accept()
        else:
            event.ignore()

    def _open_hf_download_dialog(self) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        dialog = HfDownloadDialog(settings=settings, parent=self)
        dialog.downloadRequested.connect(self._start_hf_download)
        result = dialog.exec()
        # Compatibility fallback for tests that monkeypatch dialog.exec/get_payload
        # without triggering the internal submit signal path.
        if result == dialog.DialogCode.Accepted and not dialog.was_submitted():
            self._start_hf_download(dialog.get_payload())

    def _start_hf_download(self, payload: dict) -> bool:
        self._last_hf_download_payload = dict(payload or {})
        return self.hf_transfer_controller.start_download(payload)

    def _open_hf_upload_dialog(self) -> None:
        current_json_path = str(self.dataset_explorer_controller.current_json_path or "").strip()
        if not current_json_path or not os.path.isfile(current_json_path):
            QMessageBox.warning(
                self,
                "Upload Unavailable",
                "Upload is available only when a dataset JSON is currently opened from disk.",
            )
            return

        settings = getattr(self.dataset_explorer_controller, "settings", None)
        dataset_json = getattr(self.dataset_explorer_controller, "dataset_json", {})
        hf_defaults = read_hf_source_metadata_from_dataset(dataset_json)
        dialog = HfUploadDialog(
            current_json_path,
            hf_defaults=hf_defaults,
            settings=settings,
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        upload_payload = dialog.get_payload()
        self._last_hf_upload_payload = dict(upload_payload)
        self.hf_transfer_controller.start_upload(upload_payload)

    def _on_hf_transfer_started(self, title: str, message: str, transfer_kind: str) -> None:
        self._close_hf_busy_dialog()
        self._active_hf_transfer_kind = transfer_kind
        self._hf_busy_dialog = BusyStatusDialog(title, message, self, show_cancel=True)
        self._hf_busy_dialog.cancelRequested.connect(self._on_hf_transfer_cancel_requested)
        self._hf_busy_dialog.show()
        self.show_temp_msg(title, message, 3000)

    def _on_hf_transfer_progress(self, title: str, message: str) -> None:
        if self._hf_busy_dialog:
            self._hf_busy_dialog.set_message(message)
        self.show_temp_msg(title, message, 3000)

    def _on_hf_transfer_failed(self, title: str, error: str) -> None:
        self._close_hf_busy_dialog()
        QMessageBox.critical(self, title, error)
        self.show_temp_msg(title, error, 5000)

    def _on_hf_transfer_cancel_requested(self) -> None:
        if not self._hf_busy_dialog:
            return
        self._hf_busy_dialog.set_cancel_enabled(False)
        if self._active_hf_transfer_kind == "download":
            if not self.hf_transfer_controller.cancel_download():
                self._hf_busy_dialog.set_cancel_enabled(True)
                return
            self.show_temp_msg("HF Download", "Cancelling download...", 3000)
            return
        if self._active_hf_transfer_kind == "upload":
            if not self.hf_transfer_controller.cancel_upload():
                self._hf_busy_dialog.set_cancel_enabled(True)
                return
            self.show_temp_msg("HF Upload", "Cancelling upload...", 3000)
            return
        self._hf_busy_dialog.set_cancel_enabled(True)

    def _on_hf_upload_failed(self, error: str) -> None:
        self._close_hf_busy_dialog()

        payload = dict(self._last_hf_upload_payload or {})
        repo_id = str(payload.get("repo_id") or "").strip()
        revision = str(payload.get("revision") or "main").strip() or "main"
        token = payload.get("token")
        error_text = str(error or "")
        error_lower = error_text.lower()

        repo_missing = bool(repo_id) and is_hf_repo_not_found_error(error_text)
        revision_missing = bool(repo_id and revision) and is_hf_revision_not_found_error(error_text)

        # Ambiguous HF upload errors can look like "Repository Not Found .../preupload/<revision>"
        # when the repo exists but the target branch is missing.
        is_ambiguous_branch_case = (
            not revision_missing
            and repo_missing
            and revision.lower() != "main"
            and f"/preupload/{revision.lower()}" in error_lower
        )
        if is_ambiguous_branch_case:
            try:
                revision_missing = dataset_repo_exists_on_hf(repo_id=repo_id, token=token)
                if revision_missing:
                    repo_missing = False
            except Exception:
                # Keep original classification when probing repo existence fails.
                pass

        if repo_id and revision and revision_missing:
            reply = QMessageBox.question(
                self,
                "HF Branch Not Found",
                (
                    f"The branch/revision was not found on Hugging Face:\n{repo_id}@{revision}\n\n"
                    "Do you want to create it now and retry the upload?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.show_temp_msg("HF Upload", f"Creating branch {revision} on {repo_id}...", 3000)
                    create_dataset_branch_on_hf(
                        repo_id=repo_id,
                        branch=revision,
                        source_revision="main",
                        token=token,
                    )
                except Exception as exc:
                    create_error = (
                        f"Failed to create dataset branch:\n{repo_id}@{revision}\n\n{exc}"
                    )
                    QMessageBox.critical(self, "HF Branch Creation Failed", create_error)
                    self.show_temp_msg("HF Branch Creation Failed", str(exc), 5000)
                    return

                if self.hf_transfer_controller.start_upload(payload):
                    return

                QMessageBox.critical(
                    self,
                    "HF Upload Failed",
                    "Could not restart upload because another Hugging Face upload is already running.",
                )
                self.show_temp_msg("HF Upload Failed", "Could not restart upload.", 5000)
                return

        if repo_id and repo_missing:
            reply = QMessageBox.question(
                self,
                "HF Repository Not Found",
                (
                    f"The dataset repository was not found on Hugging Face:\n{repo_id}\n\n"
                    "Do you want to create it now and retry the upload?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                try:
                    self.show_temp_msg("HF Upload", f"Creating dataset repo {repo_id}...", 3000)
                    create_dataset_repo_on_hf(repo_id=repo_id, token=token)
                except Exception as exc:
                    create_error = (
                        f"Failed to create dataset repository:\n{repo_id}\n\n{exc}"
                    )
                    QMessageBox.critical(self, "HF Repo Creation Failed", create_error)
                    self.show_temp_msg("HF Repo Creation Failed", str(exc), 5000)
                    return

                if self.hf_transfer_controller.start_upload(payload):
                    return

                QMessageBox.critical(
                    self,
                    "HF Upload Failed",
                    "Could not restart upload because another Hugging Face upload is already running.",
                )
                self.show_temp_msg("HF Upload Failed", "Could not restart upload.", 5000)
                return

        QMessageBox.critical(self, "HF Upload Failed", error)
        self.show_temp_msg("HF Upload Failed", error, 5000)

    def _on_hf_download_failed(self, error: str) -> None:
        failed_payload = dict(self._last_hf_download_payload or {})
        failed_url = str(failed_payload.get("url") or "").strip()
        if failed_url and is_hf_download_url_not_found_error(error):
            settings = getattr(self.dataset_explorer_controller, "settings", None)
            HfDownloadDialog.remove_successful_url_from_settings(settings, failed_url)

        self._last_hf_download_payload = None
        self._on_hf_transfer_failed("HF Download Failed", error)

    def _on_hf_download_cancelled(self, message: str) -> None:
        self._last_hf_download_payload = None
        self._close_hf_busy_dialog()
        QMessageBox.information(self, "HF Download Cancelled", message or "Download cancelled.")
        self.show_temp_msg("HF Download", "Download cancelled.", 3000)

    def _on_hf_download_completed(self, result: dict) -> None:
        self._close_hf_busy_dialog()
        output_dir = str(result.get("output_dir") or "")
        dry_run = bool(result.get("dry_run"))

        if dry_run:
            msg = (
                f"Dry-run completed.\n"
                f"Matched files: {result.get('referenced_file_count', 0)}\n"
                f"Estimated size: {result.get('estimated_total_size_human', '0.0 B')}\n"
                f"Output directory: {output_dir}"
            )
            QMessageBox.information(self, "HF Dry-Run Complete", msg)
            self.show_temp_msg("HF Dry-Run", "Dry-run completed.", 3000)
            self._last_hf_download_payload = None
            return

        completed_payload = dict(self._last_hf_download_payload or {})
        completed_url = str(completed_payload.get("url") or "").strip()
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        HfDownloadDialog.add_successful_url_to_settings(settings, completed_url)
        self._last_hf_download_payload = None

        download_kind = str(result.get("download_kind") or "json")
        if download_kind == "parquet":
            sample_count = int(result.get("num_samples") or 0)
            media_count = int(result.get("extracted_media_count") or 0)
            QMessageBox.information(
                self,
                "HF Download Complete",
                (
                    f"Downloaded Parquet dataset and converted it locally.\n"
                    f"Samples: {sample_count}\n"
                    f"Extracted media files: {media_count}\n"
                    f"Output directory: {output_dir}"
                ),
            )
            self.show_temp_msg(
                "HF Download",
                f"Downloaded {sample_count} samples and extracted {media_count} media files.",
                3000,
            )
        else:
            downloaded_count = int(result.get("downloaded_file_count") or 0)
            QMessageBox.information(
                self,
                "HF Download Complete",
                f"Downloaded {downloaded_count} files to:\n{output_dir}",
            )
            self.show_temp_msg("HF Download", f"Downloaded {downloaded_count} files.", 3000)

        json_path = str(result.get("json_path") or "")
        if json_path and os.path.exists(json_path):
            reply = QMessageBox.question(
                self,
                "Open Downloaded Dataset",
                "Download completed successfully.\nDo you want to open the downloaded JSON now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.dataset_explorer_controller.open_project_from_path(json_path)

    def _on_hf_upload_completed(self, result: dict) -> None:
        self._close_hf_busy_dialog()
        self._last_hf_upload_payload = None
        repo_id = str(result.get("repo_id") or "")
        revision = str(result.get("revision") or "main")
        upload_kind = str(result.get("upload_kind") or "json")
        input_file_count = int(result.get("input_file_count") or 0)
        uploaded_file_count = int(result.get("uploaded_file_count") or 0)
        sample_count = int(result.get("num_samples") or 0)
        video_file_count = int(result.get("video_file_count") or 0)
        commit_ref = str(result.get("commit_ref") or "")
        json_path = str(result.get("json_path") or "")
        json_path_in_repo = str(result.get("json_path_in_repo") or "")
        folder_name = str(result.get("folder_name") or "")
        cleaned_repo_id = repo_id.strip("/")
        cleaned_revision = revision.strip() or "main"
        dataset_url = (
            f"https://huggingface.co/datasets/{cleaned_repo_id}/tree/{cleaned_revision}"
            if cleaned_repo_id
            else ""
        )

        completion_box = QMessageBox(self)
        completion_box.setIcon(QMessageBox.Icon.Information)
        completion_box.setWindowTitle("HF Upload Complete")
        completion_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        completion_box.setTextFormat(Qt.TextFormat.RichText)
        completion_box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)

        if upload_kind == "parquet":
            completion_text = (
                f"Uploaded dataset repo content for <b>{sample_count}</b> samples:<br>"
                f"<code>{html.escape(repo_id)}</code><br>"
                f"Branch: <code>{html.escape(cleaned_revision)}</code><br>"
                f"Repository folder: <code>{html.escape(folder_name)}</code><br>"
                f"Samples converted: <b>{sample_count}</b><br>"
                f"Video files packed: <b>{video_file_count}</b><br>"
                f"Uploaded repo files: <b>{uploaded_file_count}</b><br><br>"
                f"Source JSON:<br><code>{html.escape(json_path)}</code><br><br>"
                f"Commit:<br><code>{html.escape(commit_ref)}</code>"
            )
        else:
            completion_text = (
                f"Uploaded dataset repo content for <b>{input_file_count}</b> inputs:<br>"
                f"<code>{html.escape(repo_id)}</code><br>"
                f"Branch: <code>{html.escape(cleaned_revision)}</code><br>"
                f"Input files: <b>{input_file_count}</b><br>"
                f"JSON in repo: <code>{html.escape(json_path_in_repo)}</code><br>"
                f"Uploaded repo files: <b>{uploaded_file_count}</b><br><br>"
                f"Dataset JSON:<br><code>{html.escape(json_path)}</code><br><br>"
                f"Commit:<br><code>{html.escape(commit_ref)}</code>"
            )
        if dataset_url:
            escaped_dataset_url = html.escape(dataset_url, quote=True)
            completion_text += (
                "<br><br>Dataset URL:<br>"
                f"<a href=\"{escaped_dataset_url}\">{escaped_dataset_url}</a>"
            )
        completion_box.setText(completion_text)
        for label in completion_box.findChildren(QLabel):
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            label.setOpenExternalLinks(True)
        completion_box.exec()

        if upload_kind == "parquet":
            self.show_temp_msg(
                "HF Upload",
                f"Uploaded {sample_count} samples to {repo_id}@{revision} as Parquet + WebDataset.",
                3000,
            )
        else:
            self.show_temp_msg(
                "HF Upload",
                f"Uploaded {input_file_count} inputs to {repo_id}@{revision} with dataset JSON.",
                3000,
            )

    def _on_hf_upload_cancelled(self, message: str) -> None:
        self._last_hf_upload_payload = None
        self._close_hf_busy_dialog()
        QMessageBox.information(self, "HF Upload Cancelled", message or "Upload cancelled.")
        self.show_temp_msg("HF Upload", "Upload cancelled.", 3000)

    def _close_hf_busy_dialog(self) -> None:
        if not self._hf_busy_dialog:
            self._active_hf_transfer_kind = None
            return
        self._hf_busy_dialog.close()
        self._hf_busy_dialog.deleteLater()
        self._hf_busy_dialog = None
        self._active_hf_transfer_kind = None

    def update_save_export_button_state(self) -> None:
        has_data = self.dataset_explorer_controller.json_loaded # Simple heuristic for now
        can_export = self.dataset_explorer_controller.json_loaded
        can_save = (
            can_export
            and (self.dataset_explorer_controller.current_json_path is not None)
            and self.dataset_explorer_controller.is_data_dirty
        )
        can_hf_upload = (
            bool(self.dataset_explorer_controller.json_loaded)
            and bool(self.dataset_explorer_controller.current_json_path)
            and os.path.isfile(str(self.dataset_explorer_controller.current_json_path))
        )
        self.action_save.setEnabled(can_save)
        self.action_export.setEnabled(can_export)
        self.action_undo.setEnabled(len(self.dataset_explorer_controller.undo_stack) > 0)
        self.action_redo.setEnabled(len(self.dataset_explorer_controller.redo_stack) > 0)
        if hasattr(self, "action_hf_upload"):
            self.action_hf_upload.setEnabled(can_hf_upload)
        if hasattr(self, "dataset_explorer_controller"):
            self.dataset_explorer_controller._refresh_json_preview()

    def show_temp_msg(self, title: str, msg: str, duration: int = 1500, **kwargs) -> None:
        one_line = " ".join(str(msg).splitlines()).strip()
        self.statusBar().showMessage(f"{title} — {one_line}" if title else one_line, duration)

    def _save_mute_state_to_settings(self, is_muted: bool) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if not settings:
            return
        target_state = bool(is_muted)
        current_raw = settings.value(self._MUTE_SETTING_KEY, None)
        current_state = self._coerce_setting_bool(current_raw, default=False) if current_raw is not None else None

        # If settings were externally changed since last restore, do not overwrite
        # until state has been explicitly reloaded.
        if (
            self._last_restored_mute_state is not None
            and current_state is not None
            and current_state != self._last_restored_mute_state
            and current_state != target_state
        ):
            return

        settings.setValue(self._MUTE_SETTING_KEY, target_state)
        settings.sync()
        self._last_restored_mute_state = target_state

    @staticmethod
    def _coerce_setting_bool(value, default: bool = False) -> bool:
        if isinstance(value, str):
            stripped = value.strip().lower()
            if stripped in {"1", "true", "yes", "on"}:
                return True
            if stripped in {"0", "false", "no", "off"}:
                return False
            return default
        if value is None:
            return default
        return bool(value)

    def _restore_mute_state_from_settings(self) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if not settings:
            return
        muted_raw = settings.value(self._MUTE_SETTING_KEY, False)
        should_mute = self._coerce_setting_bool(muted_raw, default=False)
        self.media_controller.set_muted(should_mute)
        self.center_panel.set_mute_button_state(self.media_controller.is_muted())
        self._last_restored_mute_state = should_mute

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
        if not self._status_filter_refresh_timer.isActive():
            self._status_filter_refresh_timer.start()

    def _refresh_filter_after_status_update(self) -> None:
        filter_idx = self.dataset_explorer_panel.filter_combo.currentIndex()
        # "Show All" does not depend on label state filtering.
        if filter_idx == 0:
            return
        self.dataset_explorer_controller.handle_filter_change(
            filter_idx
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
