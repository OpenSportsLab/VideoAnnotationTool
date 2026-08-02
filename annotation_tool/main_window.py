import copy
import html
import importlib.metadata
import json
import os

from PyQt6.QtCore import Qt, QModelIndex, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QShortcut
from PyQt6.QtWidgets import QLabel, QDockWidget, QMainWindow, QMessageBox, QStackedWidget, QTabWidget

from app_info import APP_DISPLAY_NAME, APP_VERSION, build_shortcuts_help_text
from controllers.classification import ClassificationEditorController
from controllers.hf_transfer_controller import HfTransferController
from controllers.inference_controller import InferenceController
from opensportslib.tools.hf_transfer import (
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
from ui.media_player import MediaCenterPanel, ViewerLayoutMode
from ui.classification import ClassificationAnnotationPanel
from ui.localization import LocalizationAnnotationPanel
from ui.description import DescriptionAnnotationPanel
from ui.dense_description import DenseAnnotationPanel
from ui.question_answer import QuestionAnswerAnnotationPanel
from ui.dialogs import ApplicationSettingsDialog, BusyStatusDialog, HfDownloadDialog, HfUploadDialog, InferenceRunDialog
from ui.inference_jobs_widget import InferenceJobsWidget

from media_control_settings import (
    PLAYBACK_FACTORS_KEY,
    SEEK_INTERVALS_KEY,
    load_media_control_settings,
)
from inference_settings import (
    LOCAL_MODELS_KEY,
    REMOTE_ENABLED_KEY,
    SERVER_URL_KEY,
    SHARED_MAPPINGS_KEY,
    load_last_model_choice,
    save_last_model_choice,
)
from inference_types import (
    InferenceItem,
    InferenceRequest,
    InferenceResult,
    resolve_sample_inputs,
)
from explorer_settings import EXPLORER_PAGE_SIZE_KEY, load_explorer_page_size

from utils import create_checkmark_icon, resource_path


class VideoAnnotationWindow(QMainWindow):
    """
    Main application window for annotation + localization + description + dense + Q/A workflows.
    Now directly implements the UI setup to avoid overcomplicated nesting.
    """
    _MUTE_SETTING_KEY = "media/muted"
    _VIEWER_LAYOUT_SETTING_KEY = "view/viewer_layout"
    _DATA_DOCK_VISIBLE_SETTING_KEY = "view/dataset_explorer_visible"
    _EDITOR_DOCK_VISIBLE_SETTING_KEY = "view/annotation_editor_visible"
    _INFERENCE_JOBS_DOCK_VISIBLE_SETTING_KEY = "view/inference_jobs_visible"

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(APP_DISPLAY_NAME)
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
        self.media_controller = MediaController(self.center_panel.player, self.center_panel)

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
        self.inference_controller = InferenceController(
            settings=self.dataset_explorer_controller.settings,
            base_dir=os.path.abspath(os.path.dirname(__file__)),
            parent=self,
        )
        self.action_run_inference = QAction("Run Inference…", self)
        self.action_run_inference.setEnabled(False)
        self.inference_jobs_widget = InferenceJobsWidget(
            self.action_run_inference, self
        )
        self.inference_jobs_dock = QDockWidget("Inference Jobs", self)
        self.inference_jobs_dock.setObjectName("InferenceJobsDock")
        self.inference_jobs_dock.setWidget(self.inference_jobs_widget)
        self.addDockWidget(
            Qt.DockWidgetArea.RightDockWidgetArea, self.inference_jobs_dock
        )
        self.splitDockWidget(
            self.editor_dock,
            self.inference_jobs_dock,
            Qt.Orientation.Vertical,
        )
        self.inference_jobs_dock.hide()
        self._pending_inference_requests = {}
        self._pending_prediction_samples_by_task = {}
        self._hf_busy_dialog = None
        self._active_hf_transfer_kind: str | None = None
        self._last_hf_download_payload: dict | None = None
        self._last_hf_upload_payload: dict | None = None
        self._last_restored_mute_state: bool | None = None
        self._workspace_visible = False
        self._updating_view_state = False
        self._data_dock_preferred_visible = True
        self._editor_dock_preferred_visible = True
        self._inference_jobs_dock_preferred_visible = False
        self._playback_factor_text = "2,4"
        self._seek_interval_text = "1,5"
        self._speed_rates = (0.25, 0.5, 1.0, 2.0, 4.0)
        self._seek_intervals_seconds = (1.0, 5.0)

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
        self._workspace_visible = False
        self.center_stack.setCurrentIndex(0)
        self.set_project_ui_enabled(False)
        self._set_side_docks_visible(False)
        self._set_dock_view_actions_enabled(False)
        if hasattr(self, "welcome_controller"):
            self.welcome_controller.refresh_recent_projects()

    def show_workspace(self):
        """Switch to the Media Player (Index 1 in central stack)."""
        self._workspace_visible = True
        self.center_stack.setCurrentIndex(1)
        self._set_dock_view_actions_enabled(True)
        self._apply_side_dock_preferences()
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
        self.action_run_inference.setEnabled(enabled)
        self.qa_editor_controller.set_project_enabled(enabled)
        
        # Also explicitly disable the sub-editors to be safe
        self._set_annotation_panels_enabled_for_selection(enabled)

    def _set_annotation_panels_enabled_for_selection(self, enabled: bool):
        self.classification_panel.manual_box.setEnabled(enabled)
        self.localization_panel.setEnabled(enabled)
        self.description_panel.setEnabled(enabled)
        self.dense_panel.setEnabled(enabled)
        self.qa_editor_controller.set_sample_selection_enabled(enabled)

    def _set_side_docks_visible(self, visible: bool):
        """Show or hide project dock widgets without changing their preferences."""
        self._updating_view_state = True
        try:
            self.data_dock.setVisible(visible)
            self.editor_dock.setVisible(visible)
            self.inference_jobs_dock.setVisible(visible)
        finally:
            self._updating_view_state = False

    # Welcome screen
    def _safe_import_annotations(self): self.dataset_explorer_controller.import_annotations()
    def _safe_create_project(self): self.dataset_explorer_controller.create_new_project_flow()
    def _safe_close_dataset_or_quit(self):
        if self.dataset_explorer_controller.json_loaded:
            self.dataset_explorer_controller.close_project()
        else:
            self.close()

    def _handle_input_utc_start_mutation(
        self,
        input_path: str,
        utc_text: str,
    ):
        sample_id = self.dataset_explorer_controller.current_selected_sample_id
        if not sample_id:
            return
        self.history_manager.execute_input_utc_start_update(
            sample_id,
            input_path,
            utc_text,
            self.media_controller.timeline_origin_utc(),
        )
        sources = self.dataset_explorer_controller.get_media_sources_by_id(sample_id)
        if sources:
            self.media_controller.set_sample_context(sample_id)
            self.media_controller.route_media_group(sources, input_path, False)

    def _handle_media_route(self, sources, focused_path: str, ensure_playback: bool):
        self.media_controller.set_sample_context(
            self.dataset_explorer_controller.current_selected_sample_id
        )
        self.media_controller.route_media_group(sources, focused_path, ensure_playback)
        if not focused_path:
            self.media_controller.focus_source("")

    def _handle_media_selection_route(self, sources, focused_path: str):
        preserve_playing = self.media_controller.is_playing()
        self.media_controller.set_sample_context(
            self.dataset_explorer_controller.current_selected_sample_id
        )
        self.media_controller.route_media_group(sources, focused_path, preserve_playing)
        if not focused_path:
            self.media_controller.focus_source("")

    def _handle_media_focus(self, focused_path: str):
        self.media_controller.focus_source(focused_path)

    def _handle_input_utc_start_removal(self, input_path: str):
        sample_id = self.dataset_explorer_controller.current_selected_sample_id
        if not sample_id:
            return
        self.history_manager.execute_input_utc_start_removal(
            sample_id,
            input_path,
            self.media_controller.timeline_origin_utc(),
        )
        sources = self.dataset_explorer_controller.get_media_sources_by_id(sample_id)
        if sources:
            self.media_controller.set_sample_context(sample_id)
            self.media_controller.route_media_group(sources, input_path, False)

    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # --- COMPONENT REFS ---
        center_panel = self.center_panel

        # Runtime dataset context wiring for helper services.
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
        self.dataset_explorer_controller.qaQuestionCatalogChanged.connect(
            self.qa_editor_controller.on_question_catalog_changed
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.classification_editor_controller.on_schema_context_changed
        )
        self.dataset_explorer_controller.schemaContextChanged.connect(
            self.localization_editor_controller.on_schema_context_changed
        )
        self.classification_editor_controller.inferenceRunRequested.connect(self._open_inference_run_dialog)
        self.localization_editor_controller.inferenceRunRequested.connect(self._open_inference_run_dialog)
        self.desc_editor_controller.inferenceRunRequested.connect(self._open_inference_run_dialog)
        self.dense_editor_controller.inferenceRunRequested.connect(self._open_inference_run_dialog)
        self.qa_editor_controller.inferenceRunRequested.connect(self._open_inference_run_dialog)
        self.action_run_inference.triggered.connect(
            self._request_inference_for_active_mode
        )
        self.inference_jobs_widget.cancelRequested.connect(
            self.inference_controller.cancel_request
        )
        self.inference_jobs_widget.cancelAllRequested.connect(
            self.inference_controller.cancel_all
        )
        self.inference_jobs_widget.clearHistoryRequested.connect(
            self.inference_controller.clear_queue_history
        )
        for task_name, controller in (
            ("classification", self.classification_editor_controller),
            ("localization", self.localization_editor_controller),
            ("description", self.desc_editor_controller),
            ("dense_description", self.dense_editor_controller),
            ("question_answer", self.qa_editor_controller),
        ):
            controller.pendingPredictionsChanged.connect(
                lambda sample_ids, task=task_name: self._on_pending_predictions_changed(task, sample_ids)
            )
        self.inference_controller.inferenceCompleted.connect(self._on_shared_inference_completed)
        self.inference_controller.inferenceFailed.connect(self._on_shared_inference_failed)
        self.inference_controller.inferenceCancelled.connect(self._on_shared_inference_cancelled)
        self.inference_controller.queueChanged.connect(
            self.inference_jobs_widget.set_entries
        )
        self.dataset_explorer_controller.mediaRouteRequested.connect(
            self._handle_media_route
        )
        self.dataset_explorer_controller.mediaSelectionRouteRequested.connect(
            self._handle_media_selection_route
        )
        self.dataset_explorer_controller.mediaFocusRequested.connect(
            self._handle_media_focus
        )
        self.media_controller.timelineOriginChanged.connect(
            self.history_manager.on_timeline_origin_changed
        )
        self.media_controller.timelineOriginChanged.connect(
            self.localization_editor_controller.on_timeline_origin_changed
        )
        self.media_controller.timelineOriginChanged.connect(
            self.dense_editor_controller.on_timeline_origin_changed
        )
        self.media_controller.inputUtcStartMutationRequested.connect(
            self._handle_input_utc_start_mutation
        )
        self.media_controller.inputUtcStartRemovalRequested.connect(
            self._handle_input_utc_start_removal
        )
        self.dataset_explorer_controller.mediaStopRequested.connect(lambda: self.media_controller.stop())
        self.dataset_explorer_controller.mediaResetRequested.connect(self.media_controller.reset_viewers)
        self.dataset_explorer_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.dataset_explorer_controller.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.dataset_explorer_controller.saveStateRefreshRequested.connect(
            self.dataset_explorer_controller._refresh_json_preview
        )
        self.dataset_explorer_controller.schemaRefreshRequested.connect(self._refresh_schema_panels)
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
        self.dataset_explorer_controller.ballH5AssociationMutationRequested.connect(
            self.history_manager.execute_set_ball_h5_association
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            lambda _settings: self._restore_mute_state_from_settings()
        )
        self.dataset_explorer_controller.projectGenerationChanged.connect(
            self._on_project_generation_changed
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            lambda _settings: self._restore_view_state_from_settings()
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            lambda _settings: self._restore_media_controls_from_settings()
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            lambda _settings: self._restore_explorer_settings_from_settings()
        )
        self.dataset_explorer_controller.settingsChanged.connect(
            self.localization_editor_controller.set_settings
        )
        self.localization_editor_controller.set_settings(self.dataset_explorer_controller.settings)


        # --- Center panel (Unified Playback) ---
        center_panel.playPauseRequested.connect(self.media_controller.toggle_play_pause)
        center_panel.muteToggleRequested.connect(self.media_controller.toggle_mute)
        center_panel.seekRequested.connect(lambda ms: self.media_controller.set_position(ms))
        center_panel.seekRelativeRequested.connect(self.media_controller.seek_relative)
        center_panel.stopRequested.connect(lambda: self.media_controller.stop())
        center_panel.playbackRateRequested.connect(lambda rate: self.media_controller.set_playback_rate(rate))
        self.media_controller.positionChanged.connect(center_panel.on_media_position_changed)
        self.media_controller.durationChanged.connect(center_panel.on_media_duration_changed)
        self.media_controller.playbackStateChanged.connect(self.localization_editor_controller.on_playback_state_changed)
        center_panel.positionChanged.connect(self.localization_editor_controller.on_media_position_changed)
        center_panel.durationChanged.connect(self.localization_editor_controller.on_media_duration_changed)
        center_panel.positionChanged.connect(self.dense_editor_controller.on_media_position_changed)
        self.media_controller.muteStateChanged.connect(center_panel.set_mute_button_state)
        self.media_controller.muteStateChanged.connect(self._save_mute_state_to_settings)
        center_panel.set_mute_button_state(self.media_controller.is_muted())
        self._restore_mute_state_from_settings()
        self._restore_media_controls_from_settings()
        self._restore_explorer_settings_from_settings()
        # Dense add should always pause playback first; no auto-resume behavior.
        self.dense_panel.addEventRequested.connect(self.media_controller.pause)
        # Snapshot runtime media position on dense actions.
        self.dense_panel.addEventRequested.connect(
            lambda: self.dense_editor_controller.on_media_position_changed(self.media_controller.current_position_ms())
        )
        self.dense_panel.updateTimeForSelectedRequested.connect(
            lambda _event: self.dense_editor_controller.on_media_position_changed(self.media_controller.current_position_ms())
        )
        self.dense_panel.eventNavigateRequested.connect(
            lambda _step: self.dense_editor_controller.on_media_position_changed(self.media_controller.current_position_ms())
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
        self.localization_editor_controller.mediaSeekRequested.connect(
            lambda ms: self.media_controller.set_position(ms)
        )
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
        self.dense_editor_controller.denseEventsSetRequested.connect(
            self.history_manager.execute_dense_events_set
        )
        self.dense_editor_controller.mediaSeekRequested.connect(
            lambda ms: self.media_controller.set_position(ms)
        )
        self.dense_editor_controller.markersUpdateRequested.connect(self.center_panel.set_markers)

        self.qa_editor_controller.statusMessageRequested.connect(self.show_temp_msg)
        self.qa_editor_controller.qaAnswersUpdateRequested.connect(
            self.history_manager.execute_qa_answers_update
        )

        # --- History manager request signals ---
        self.history_manager.allItemStatusRefreshRequested.connect(self.dataset_explorer_controller.refresh_all_item_statuses)
        self.history_manager.saveStateRefreshRequested.connect(self.update_save_export_button_state)
        self.history_manager.saveStateRefreshRequested.connect(
            self.dataset_explorer_controller._refresh_json_preview
        )
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
        from PyQt6.QtGui import QActionGroup
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

        edit_menu.addSeparator()
        self.action_settings = QAction("Settings…", self)
        self.action_settings.setMenuRole(QAction.MenuRole.PreferencesRole)
        self.action_settings.triggered.connect(self._open_settings_dialog)
        edit_menu.addAction(self.action_settings)

        view_menu = menu_bar.addMenu("&View")

        self.action_show_dataset_explorer = QAction("Dataset Explorer", self)
        self.action_show_dataset_explorer.setCheckable(True)
        self.action_show_dataset_explorer.toggled.connect(
            lambda visible: self._set_dock_preference("data", visible)
        )
        view_menu.addAction(self.action_show_dataset_explorer)

        self.action_show_annotation_editor = QAction("Annotation Editor", self)
        self.action_show_annotation_editor.setCheckable(True)
        self.action_show_annotation_editor.toggled.connect(
            lambda visible: self._set_dock_preference("editor", visible)
        )
        view_menu.addAction(self.action_show_annotation_editor)

        self.action_show_inference_jobs = self.inference_jobs_dock.toggleViewAction()
        self.action_show_inference_jobs.setText("Inference Jobs")
        view_menu.addAction(self.action_show_inference_jobs)

        view_menu.addSeparator()
        layout_menu = view_menu.addMenu("Viewer Layout")
        self.viewer_layout_action_group = QActionGroup(self)
        self.viewer_layout_action_group.setExclusive(True)
        self.viewer_layout_actions = {}
        for label, mode in (
            ("Single Modality", ViewerLayoutMode.SINGLE),
            ("Mosaic", ViewerLayoutMode.MOSAIC),
            ("Modality Tabs", ViewerLayoutMode.TABS),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(mode.value)
            action.triggered.connect(
                lambda checked, selected_mode=mode: self._set_viewer_layout(selected_mode)
                if checked else None
            )
            self.viewer_layout_action_group.addAction(action)
            self.viewer_layout_actions[mode] = action
            layout_menu.addAction(action)

        self.data_dock.visibilityChanged.connect(
            lambda visible: self._on_dock_visibility_changed("data", visible)
        )
        self.editor_dock.visibilityChanged.connect(
            lambda visible: self._on_dock_visibility_changed("editor", visible)
        )
        self.inference_jobs_dock.visibilityChanged.connect(
            lambda visible: self._on_dock_visibility_changed("inference", visible)
        )
        self._restore_view_state_from_settings()

        help_menu = menu_bar.addMenu("&Help")

        self.action_shortcuts = QAction("Shortcuts", self)
        self.action_shortcuts.triggered.connect(self._show_shortcuts_popup)
        help_menu.addAction(self.action_shortcuts)

        self.action_info = QAction("Info", self)
        self.action_info.triggered.connect(self._show_info_popup)
        help_menu.addAction(self.action_info)

    @staticmethod
    def _setting_bool(value, default: bool) -> bool:
        if value is None:
            return bool(default)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
            return bool(default)
        return bool(value)

    def _restore_view_state_from_settings(self) -> None:
        if not hasattr(self, "viewer_layout_actions"):
            return
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is None:
            return

        self._data_dock_preferred_visible = self._setting_bool(
            settings.value(self._DATA_DOCK_VISIBLE_SETTING_KEY, True), True
        )
        self._editor_dock_preferred_visible = self._setting_bool(
            settings.value(self._EDITOR_DOCK_VISIBLE_SETTING_KEY, True), True
        )
        self._inference_jobs_dock_preferred_visible = self._setting_bool(
            settings.value(self._INFERENCE_JOBS_DOCK_VISIBLE_SETTING_KEY, False),
            False,
        )
        raw_mode = str(
            settings.value(
                self._VIEWER_LAYOUT_SETTING_KEY,
                ViewerLayoutMode.MOSAIC.value,
            )
            or ""
        )
        try:
            mode = ViewerLayoutMode(raw_mode)
        except ValueError:
            mode = ViewerLayoutMode.MOSAIC

        self._updating_view_state = True
        try:
            self.action_show_dataset_explorer.setChecked(self._data_dock_preferred_visible)
            self.action_show_annotation_editor.setChecked(self._editor_dock_preferred_visible)
            self.action_show_inference_jobs.setChecked(
                self._inference_jobs_dock_preferred_visible
            )
            self.viewer_layout_actions[mode].setChecked(True)
            self.center_panel.set_viewer_layout(mode)
            if self._workspace_visible:
                self.data_dock.setVisible(self._data_dock_preferred_visible)
                self.editor_dock.setVisible(self._editor_dock_preferred_visible)
                self.inference_jobs_dock.setVisible(
                    self._inference_jobs_dock_preferred_visible
                )
        finally:
            self._updating_view_state = False

    def _set_viewer_layout(self, mode: ViewerLayoutMode) -> None:
        self.center_panel.set_viewer_layout(mode)
        if self._updating_view_state:
            return
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is not None:
            settings.setValue(self._VIEWER_LAYOUT_SETTING_KEY, mode.value)
            settings.sync()

    def _set_dock_preference(self, dock_name: str, visible: bool) -> None:
        target = bool(visible)
        if dock_name == "data":
            self._data_dock_preferred_visible = target
            setting_key = self._DATA_DOCK_VISIBLE_SETTING_KEY
            dock = self.data_dock
        elif dock_name == "editor":
            self._editor_dock_preferred_visible = target
            setting_key = self._EDITOR_DOCK_VISIBLE_SETTING_KEY
            dock = self.editor_dock
        else:
            self._inference_jobs_dock_preferred_visible = target
            setting_key = self._INFERENCE_JOBS_DOCK_VISIBLE_SETTING_KEY
            dock = self.inference_jobs_dock
        if self._updating_view_state:
            return
        if self._workspace_visible:
            self._updating_view_state = True
            try:
                dock.setVisible(target)
            finally:
                self._updating_view_state = False
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is not None:
            settings.setValue(setting_key, target)
            settings.sync()

    def _on_dock_visibility_changed(self, dock_name: str, visible: bool) -> None:
        if self._updating_view_state or not self._workspace_visible:
            return
        actions = {
            "data": self.action_show_dataset_explorer,
            "editor": self.action_show_annotation_editor,
            "inference": self.action_show_inference_jobs,
        }
        action = actions[dock_name]
        self._updating_view_state = True
        try:
            action.setChecked(bool(visible))
        finally:
            self._updating_view_state = False
        self._set_dock_preference(dock_name, visible)

    def _apply_side_dock_preferences(self) -> None:
        self._updating_view_state = True
        try:
            self.data_dock.setVisible(self._data_dock_preferred_visible)
            self.editor_dock.setVisible(self._editor_dock_preferred_visible)
            self.inference_jobs_dock.setVisible(
                self._inference_jobs_dock_preferred_visible
            )
        finally:
            self._updating_view_state = False

    def _set_dock_view_actions_enabled(self, enabled: bool) -> None:
        if hasattr(self, "action_show_dataset_explorer"):
            self.action_show_dataset_explorer.setEnabled(enabled)
            self.action_show_annotation_editor.setEnabled(enabled)
            self.action_show_inference_jobs.setEnabled(enabled)

    def _setup_shortcuts(self) -> None:
        """Register common keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self._safe_import_annotations)
        
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self.dataset_explorer_controller.save_project)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(
            self.dataset_explorer_controller.export_project
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
            lambda: self.media_controller.step_frame(-1)
        )
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(
            lambda: self.media_controller.step_frame(1)
        )
        self.shortcut_seek_back_primary = QShortcut(QKeySequence("Ctrl+Left"), self)
        self.shortcut_seek_fwd_primary = QShortcut(QKeySequence("Ctrl+Right"), self)
        self.shortcut_seek_back_secondary = QShortcut(QKeySequence("Ctrl+Shift+Left"), self)
        self.shortcut_seek_fwd_secondary = QShortcut(QKeySequence("Ctrl+Shift+Right"), self)
        self.shortcut_seek_back_primary.activated.connect(
            lambda: self._seek_by_configured_interval(0, -1)
        )
        self.shortcut_seek_fwd_primary.activated.connect(
            lambda: self._seek_by_configured_interval(0, 1)
        )
        self.shortcut_seek_back_secondary.activated.connect(
            lambda: self._seek_by_configured_interval(1, -1)
        )
        self.shortcut_seek_fwd_secondary.activated.connect(
            lambda: self._seek_by_configured_interval(1, 1)
        )
        self._update_media_shortcut_state()

    def _show_shortcuts_popup(self) -> None:
        QMessageBox.information(
            self,
            "Shortcuts",
            build_shortcuts_help_text(self._seek_intervals_seconds),
        )

    def _open_settings_dialog(self) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        dialog = ApplicationSettingsDialog(
            self._playback_factor_text,
            self._seek_interval_text,
            self.dataset_explorer_controller.tree_model.page_size(),
            settings=settings,
            parent=self,
        )
        dialog.mediaControlsApplyRequested.connect(self._save_and_apply_media_controls)
        dialog.explorerPageSizeApplyRequested.connect(
            self._save_and_apply_explorer_page_size
        )
        dialog.inferenceSettingsApplyRequested.connect(self._save_inference_settings)
        dialog.inferenceTestRequested.connect(lambda: self._test_inference_connection(dialog))
        dialog.inferenceRemoteCatalogRequested.connect(
            lambda: self._refresh_remote_model_catalog(dialog)
        )
        catalog_slot = lambda models: dialog.set_remote_model_catalog(models)
        catalog_error_slot = lambda message: dialog.set_inference_connection_status(message, False)
        self.inference_controller.remoteCatalogDiscovered.connect(catalog_slot)
        self.inference_controller.remoteCatalogFailed.connect(catalog_error_slot)
        dialog.exec()
        try:
            self.inference_controller.remoteCatalogDiscovered.disconnect(catalog_slot)
            self.inference_controller.remoteCatalogFailed.disconnect(catalog_error_slot)
        except Exception:
            pass

    def _save_inference_settings(self, payload: dict) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is None:
            return
        settings.setValue(REMOTE_ENABLED_KEY, bool(payload.get("remote_enabled", False)))
        settings.setValue(SERVER_URL_KEY, str(payload.get("server_url") or ""))
        settings.setValue(SHARED_MAPPINGS_KEY, json.dumps(list(payload.get("shared_mappings") or [])))
        settings.setValue(LOCAL_MODELS_KEY, json.dumps(list(payload.get("local_models") or [])))
        settings.sync()

    def _refresh_remote_model_catalog(self, dialog) -> None:
        try:
            config = dialog.inference_payload()
        except ValueError as exc:
            dialog.set_inference_connection_status(str(exc), False)
            return
        if not config.get("remote_enabled", False):
            dialog.set_inference_connection_status(
                "Enable remote inference before refreshing models.", False
            )
            return
        dialog.set_inference_connection_status("Discovering remote models…", True)
        if not self.inference_controller.request_remote_catalog(config):
            dialog.set_inference_connection_status(
                "Another model discovery request is still running.", False
            )

    def _test_inference_connection(self, dialog) -> None:
        try:
            config = dialog.inference_payload()
            if not config.get("remote_enabled", False):
                dialog.set_inference_connection_status(
                    "Enable remote inference before testing the connection.", False
                )
                return
            capabilities = self.inference_controller.test_connection(config)
            version = str(capabilities.get("version") or "unknown")
            shared_roots = list(capabilities.get("shared_roots") or [])
            root_ids = [str(root.get("id") or "") for root in shared_roots if isinstance(root, dict) and root.get("id")]
            root_text = f" Available root IDs: {', '.join(root_ids)}." if root_ids else ""
            dialog.set_inference_connection_status(
                f"Connected to API version {version}; {len(shared_roots)} shared root(s) advertised.{root_text}", True
            )
        except Exception as exc:
            dialog.set_inference_connection_status(str(exc), False)

    def _request_inference_for_active_mode(self) -> None:
        controllers = (
            self.classification_editor_controller,
            self.localization_editor_controller,
            self.desc_editor_controller,
            self.dense_editor_controller,
            self.qa_editor_controller,
        )
        index = self.right_tabs.currentIndex()
        if index < 0 or index >= len(controllers):
            QMessageBox.warning(
                self, "Inference", "Select an annotation mode first."
            )
            return
        controllers[index].request_inference()

    def _open_inference_run_dialog(self, task: str, context) -> None:
        context = dict(context or {})
        current_sample_id = str(self.dataset_explorer_controller.current_selected_sample_id or "")
        sample_ids = list(context.get("batch_sample_ids") or [current_sample_id])
        if task == "classification" and not context.get("batch_sample_ids"):
            available = [str(sample.get("id") or "") for sample in self.dataset_explorer_controller.dataset_json.get("data", []) if isinstance(sample, dict) and sample.get("id")]
            if available:
                sample_ids = available
                context["available_batch_sample_ids"] = available
                context["current_sample_id"] = current_sample_id
        samples = [
            self.dataset_explorer_controller.get_sample(str(sample_id))
            for sample_id in sample_ids
        ]
        samples = [sample for sample in samples if isinstance(sample, dict)]
        if not samples:
            QMessageBox.warning(self, "Inference", "Please select a sample first.")
            return
        inputs_by_sample = {
            str(sample.get("id") or ""): resolve_sample_inputs(
                sample, str(self.dataset_explorer_controller.current_json_path or "")
            )
            for sample in samples
        }
        for sample_id, sample_inputs in inputs_by_sample.items():
            for source in sample_inputs:
                source.sample_id = sample_id
        inputs = [source for sample_inputs in inputs_by_sample.values() for source in sample_inputs]
        dialog_inputs = (
            list(inputs_by_sample.get(current_sample_id, []))
            if task == "classification"
            else inputs
        )
        if not dialog_inputs:
            QMessageBox.warning(self, "Inference", "The selected sample has no usable inputs.")
            return

        dialog = InferenceRunDialog(
            task,
            dialog_inputs,
            context,
            preferred_model=load_last_model_choice(
                getattr(self.dataset_explorer_controller, "settings", None), task
            ),
            parent=self,
        )
        def refresh_models(selected_task: str):
            dialog.set_models([])
            dialog.availability_label.setText("Discovering models…")
            if not self.inference_controller.request_model_catalog(selected_task):
                dialog.availability_label.setText("Another model discovery request is still running.")

        dialog.refreshModelsRequested.connect(refresh_models)
        def apply_catalog(discovered_task, choices, warning):
            if discovered_task != task:
                return
            input_types = {source.type for source in dialog_inputs}
            dialog.set_models(
                [
                    choice
                    for choice in choices
                    if not choice.descriptor.accepted_input_types
                    or not input_types.isdisjoint(choice.descriptor.accepted_input_types)
                ],
                warning,
            )

        def show_catalog_error(discovered_task, message):
            if discovered_task == task:
                dialog.set_models([], message)

        self.inference_controller.modelCatalogDiscovered.connect(apply_catalog)
        self.inference_controller.modelCatalogFailed.connect(show_catalog_error)
        refresh_models(task)
        dialog_result = dialog.exec()
        try:
            self.inference_controller.modelCatalogDiscovered.disconnect(apply_catalog)
            self.inference_controller.modelCatalogFailed.disconnect(show_catalog_error)
        except Exception:
            pass
        if dialog_result != dialog.DialogCode.Accepted:
            return
        payload = dialog.payload()
        parameters = {
            key: value for key, value in payload.items()
            if key in {"start_ms", "end_ms", "language", "question"}
            and value not in (None, "")
        }
        if task in {"classification", "localization"}:
            parameters["head"] = str(context.get("head") or "")
        if task == "localization":
            parameters["labels"] = list(context.get("labels") or [])
        selected_sources = {(str(getattr(source, "sample_id", "") or ""), os.path.realpath(source.path)) for source in payload["inputs"]}
        classification_input_indices = []
        if task == "classification":
            selected_paths = {
                os.path.realpath(source.path) for source in payload["inputs"]
            }
            classification_input_indices = [
                index
                for index, source in enumerate(dialog_inputs)
                if os.path.realpath(source.path) in selected_paths
            ]
        if payload.get("scope") == "current":
            samples = [sample for sample in samples if str(sample.get("id") or "") == current_sample_id]
        request_items = []
        for sample in samples:
            sample_id = str(sample.get("id") or "")
            sample_inputs = inputs_by_sample.get(sample_id, [])
            if task == "classification":
                selected_inputs = [
                    sample_inputs[index]
                    for index in classification_input_indices
                    if index < len(sample_inputs)
                    and sample_inputs[index].type == dialog_inputs[index].type
                ]
            else:
                selected_inputs = [
                    source for source in sample_inputs
                    if (sample_id, os.path.realpath(source.path)) in selected_sources
                ]
            if selected_inputs:
                request_items.append(InferenceItem(
                    sample_id=sample_id,
                    inputs=selected_inputs,
                    sample=copy.deepcopy(sample),
                ))
        if not request_items or len(request_items) != len(samples):
            QMessageBox.warning(self, "Inference", "Every batch sample must retain at least one input.")
            return
        request = InferenceRequest(
            task=task,
            model_id=payload["model_id"],
            backend=payload["backend"],
            provider_config=copy.deepcopy(
                self.inference_controller.configuration_snapshot()
            ),
            target_context=copy.deepcopy(context),
            schema=copy.deepcopy(self.dataset_explorer_controller.label_definitions),
            parameters=parameters,
            items=request_items,
        )
        self._pending_inference_requests[request.request_id] = {
            "task": task,
            "sample_ids": tuple(item.sample_id for item in request.items),
            "request_items": {
                item.item_id: item.sample_id for item in request.items
            },
            "project_generation": self.dataset_explorer_controller.project_generation,
            "context": copy.deepcopy(parameters),
            "backend": payload["backend"],
            "model_id": payload["model_id"],
            "invalidated": False,
        }
        entry = self.inference_controller.enqueue_inference(request)
        if entry is None:
            self._pending_inference_requests.pop(request.request_id, None)
            QMessageBox.information(self, "Inference", "The inference request could not be queued.")
            return
        self._show_inference_jobs()
        if entry.state == "queued":
            self.show_temp_msg(
                "Inference",
                f"Added to the {entry.backend.title()} queue at position {entry.queue_position}.",
                2500,
            )
        elif entry.state == "running":
            self.show_temp_msg(
                "Inference", f"Started {entry.backend.title()} inference.", 1800
            )

    def _on_shared_inference_completed(self, request_id: str, result) -> None:
        pending = self._pending_inference_requests.pop(request_id, None)
        if not pending:
            return
        if (
            pending.get("invalidated")
            or pending.get("project_generation")
            != self.dataset_explorer_controller.project_generation
        ):
            self.show_temp_msg(
                "Inference",
                "Discarded results from the previous project.",
                3000,
            )
            return
        save_last_model_choice(
            getattr(self.dataset_explorer_controller, "settings", None),
            pending["task"],
            pending.get("backend", ""),
            pending.get("model_id", ""),
        )
        request_items = dict(pending.get("request_items") or {})
        surviving_items = tuple(
            item
            for item in result.items
            if request_items.get(str(item.get("item_id") or ""))
            == str(item.get("sample_id") or "")
            and self.dataset_explorer_controller.get_sample(
                str(item.get("sample_id") or "")
            )
            is not None
        )
        discarded_count = len(result.items) - len(surviving_items)
        if not surviving_items:
            self.show_temp_msg(
                "Inference",
                "Results were discarded because their original sample no longer exists.",
                3500,
            )
            return
        if surviving_items != result.items:
            result = InferenceResult(
                request_id=result.request_id,
                task=result.task,
                model_id=result.model_id,
                items=surviving_items,
            )
        handlers = {
            "classification": self.classification_editor_controller.apply_shared_inference_result,
            "localization": self.localization_editor_controller.apply_shared_inference_result,
            "description": self.desc_editor_controller.apply_shared_inference_result,
            "dense_description": self.dense_editor_controller.apply_shared_inference_result,
            "question_answer": self.qa_editor_controller.apply_shared_inference_result,
        }
        active_annotation_tab = self.right_tabs.currentIndex()
        active_classification_head = self.classification_panel.get_current_head()
        active_localization_head = (
            self.localization_panel.annot_mgmt.tabs.get_current_head()
        )
        try:
            handlers[pending["task"]](result, pending.get("context", {}))
        except Exception as exc:
            QMessageBox.critical(self, "Inference Result Error", str(exc))
            return
        finally:
            if self.right_tabs.currentIndex() != active_annotation_tab:
                self.right_tabs.setCurrentIndex(active_annotation_tab)
            if (
                active_classification_head
                and self.classification_panel.get_current_head()
                != active_classification_head
            ):
                self.classification_panel.set_current_head(
                    active_classification_head
                )
            if (
                active_localization_head
                and self.localization_panel.annot_mgmt.tabs.get_current_head()
                != active_localization_head
            ):
                self.localization_panel.annot_mgmt.tabs.set_current_head(
                    active_localization_head
                )
        sample_ids = tuple(
            str(item.get("sample_id") or "") for item in surviving_items
        )
        if len(sample_ids) == 1:
            message = f"Predictions are ready for sample {sample_ids[0]}."
        else:
            message = f"Predictions are ready for {len(sample_ids)} samples."
        if discarded_count:
            message += f" {discarded_count} removed sample result(s) were discarded."
        self.show_temp_msg("Inference", message, 3500)

    def _on_pending_predictions_changed(self, task: str, sample_ids) -> None:
        task = str(task)
        pending_sample_ids = {str(value) for value in sample_ids or [] if str(value)}
        if self._pending_prediction_samples_by_task.get(task, set()) == pending_sample_ids:
            return
        self._pending_prediction_samples_by_task[task] = pending_sample_ids
        combined = set().union(*self._pending_prediction_samples_by_task.values()) if self._pending_prediction_samples_by_task else set()
        self.dataset_explorer_controller.set_pending_prediction_samples(combined)

    def _on_shared_inference_failed(self, request_id, message, code, retryable, details) -> None:
        pending = self._pending_inference_requests.pop(request_id, None)
        if not pending or pending.get("invalidated"):
            return
        self._show_inference_jobs()
        retry_text = " The operation may be retried." if retryable else ""
        self.show_temp_msg(
            "Inference Error",
            f"{message}{retry_text} Code: {code}. See Inference Jobs.",
            6000,
        )

    def _show_inference_jobs(self) -> None:
        self.inference_jobs_dock.show()
        self.inference_jobs_dock.raise_()

    def _on_shared_inference_cancelled(self, request_id: str) -> None:
        pending = self._pending_inference_requests.pop(request_id, None)
        if not pending or pending.get("invalidated"):
            return
        self.show_temp_msg("Inference", "Inference cancelled.", 1500)

    def _on_project_generation_changed(self, _generation: int) -> None:
        if not self._pending_inference_requests:
            return
        for pending in self._pending_inference_requests.values():
            pending["invalidated"] = True
        self.inference_controller.cancel_all()

    def _save_and_apply_explorer_page_size(self, page_size: int) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is not None:
            settings.setValue(EXPLORER_PAGE_SIZE_KEY, int(page_size))
            settings.sync()
        self.dataset_explorer_controller.set_explorer_page_size(page_size)

    def _restore_explorer_settings_from_settings(self) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        self.dataset_explorer_controller.set_explorer_page_size(
            load_explorer_page_size(settings)
        )

    def _save_and_apply_media_controls(
        self,
        factor_text: str,
        interval_text: str,
        speed_rates,
        seek_intervals,
    ) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is not None:
            settings.setValue(PLAYBACK_FACTORS_KEY, factor_text)
            settings.setValue(SEEK_INTERVALS_KEY, interval_text)
            settings.sync()
        self._apply_media_controls(
            factor_text,
            interval_text,
            speed_rates,
            seek_intervals,
        )

    def _restore_media_controls_from_settings(self) -> None:
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        if settings is None:
            return
        factors, intervals = load_media_control_settings(settings)
        self._apply_media_controls(
            factors.normalized_text,
            intervals.normalized_text,
            factors.values,
            intervals.values,
        )

    def _apply_media_controls(
        self,
        factor_text: str,
        interval_text: str,
        speed_rates,
        seek_intervals,
    ) -> None:
        rates = tuple(float(value) for value in speed_rates)
        intervals = tuple(float(value) for value in seek_intervals)
        active_rate = self.media_controller.playback_rate()

        self._playback_factor_text = factor_text
        self._seek_interval_text = interval_text
        self._speed_rates = rates
        self._seek_intervals_seconds = intervals
        self.center_panel.configure_playback_controls(rates, intervals)

        if not any(abs(active_rate - rate) < 0.0005 for rate in rates):
            self.media_controller.set_playback_rate(1.0)
        self._update_media_shortcut_state()

    def _seek_by_configured_interval(self, index: int, direction: int) -> None:
        if index >= len(self._seek_intervals_seconds):
            return
        delta_ms = round(self._seek_intervals_seconds[index] * 1000) * int(direction)
        self.media_controller.seek_relative(delta_ms)

    def _update_media_shortcut_state(self) -> None:
        if not hasattr(self, "shortcut_seek_back_primary"):
            return
        has_primary = bool(self._seek_intervals_seconds)
        has_secondary = len(self._seek_intervals_seconds) > 1
        self.shortcut_seek_back_primary.setEnabled(has_primary)
        self.shortcut_seek_fwd_primary.setEnabled(has_primary)
        self.shortcut_seek_back_secondary.setEnabled(has_secondary)
        self.shortcut_seek_fwd_secondary.setEnabled(has_secondary)

    def _show_info_popup(self) -> None:
        try:
            osl_version = importlib.metadata.version("opensportslib")
        except importlib.metadata.PackageNotFoundError:
            osl_version = "not installed"
        QMessageBox.information(self, "Info", f"{APP_DISPLAY_NAME}\nVersion: {APP_VERSION}\nOpenSportsLib: {osl_version}")

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
            if not self.inference_controller.shutdown(wait_ms=3000):
                self.show_temp_msg(
                    "Inference Running",
                    "Shared inference is still stopping. Please wait and close again.",
                    2500,
                )
                event.ignore()
                return
            self._pending_inference_requests.clear()
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
            self._workspace_visible = False
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
        if failed_payload and is_hf_download_url_not_found_error(error):
            settings = getattr(self.dataset_explorer_controller, "settings", None)
            HfDownloadDialog.remove_successful_transfer_from_settings(settings, failed_payload)

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
        settings = getattr(self.dataset_explorer_controller, "settings", None)
        HfDownloadDialog.add_successful_transfer_to_settings(settings, completed_payload)
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
                f"Input files packed: <b>{input_file_count}</b><br>"
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
        self.dataset_explorer_controller._json_preview_dirty = True
        self.dataset_explorer_controller.refresh_all_item_statuses()
        self.dataset_explorer_controller.handle_filter_change(
            self.dataset_explorer_panel.filter_combo.currentIndex(),
            selection_fallback=filter_selection_fallback,
        )

        if action_path:
            idx = self.dataset_explorer_controller._index_for_path(action_path)
            if idx.isValid() and self.dataset_explorer_panel.tree.currentIndex() != idx:
                self.dataset_explorer_panel.tree.setCurrentIndex(idx)

        self.dataset_explorer_controller.reemit_current_selection()
        self.dataset_explorer_controller._refresh_json_preview()

        self.update_save_export_button_state()
