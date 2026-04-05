import os

from PyQt6.QtCore import Qt, QTimer, QModelIndex, QUrl
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QShortcut, QStandardItem
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import (
    QMainWindow, QMessageBox, QSizePolicy, QStackedWidget, QDockWidget, QTabWidget, QWidget, QVBoxLayout
)

from controllers.classification.class_annotation_manager import AnnotationManager
from controllers.classification.class_navigation_manager import NavigationManager
from controllers.classification.inference_manager import InferenceManager
from controllers.classification.train_manager import TrainManager
from controllers.localization.localization_manager import LocalizationManager
from controllers.description.desc_navigation_manager import DescNavigationManager
from controllers.description.desc_annotation_manager import DescAnnotationManager
from controllers.dense_description.dense_manager import DenseManager
from controllers.history_manager import HistoryManager
from controllers.media_controller import MediaController

from controllers.router import AppRouter
from models import AppStateModel

# [NEW] Direct UI Imports
from ui.common.welcome_widget import WelcomeWidget
from ui.common.clip_explorer import CommonProjectTreePanel
from ui.localization.media_player import LocCenterPanel
from ui.classification.event_editor import ClassificationAnnotationPanel
from ui.localization.event_editor import LocalizationAnnotationPanel
from ui.description.event_editor import DescriptionAnnotationPanel
from ui.dense_description.event_editor import DenseAnnotationPanel

from models.project_tree import ProjectTreeModel
from utils import create_checkmark_icon, natural_sort_key, resource_path

class VideoAnnotationWindow(QMainWindow):
    """
    Main application window for annotation + localization + description + dense workflows.
    Now directly implements the UI setup to avoid overcomplicated nesting.
    """

    FILTER_ALL = 0
    FILTER_DONE = 1
    FILTER_NOT_DONE = 2

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Video Annotation Tool")
        self.resize(1200, 800)

        # --- Model wiring ---
        self.model = AppStateModel()
        self.tree_model = ProjectTreeModel(self)

        # --- 1. Center Area: Stacked Widget (Welcome vs Media Player) ---
        self.center_stack = QStackedWidget()
        
        self.welcome_widget = WelcomeWidget()
        self.center_stack.addWidget(self.welcome_widget)
        
        self.center_panel = LocCenterPanel()
        self.center_stack.addWidget(self.center_panel)
        
        self.setCentralWidget(self.center_stack)

        # --- 2. Left Dock: Project Navigator ---
        self.left_panel = CommonProjectTreePanel(
            tree_title="Data",
            filter_items=["Show All", "Hand Labelled", "Smart Labelled", "No Labelled"],
            clear_text="Clear All",
            enable_context_menu=True
        )
        self.left_panel.tree.setModel(self.tree_model)
        
        self.data_dock = QDockWidget("Project Navigator", self)
        self.data_dock.setObjectName("DataNavigatorDock")
        self.data_dock.setWidget(self.left_panel)
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

        # Allow nested docking and tabbed docks
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AnimatedDocks)

        # --- Controllers ---
        self.router = AppRouter(self)
        self.history_manager = HistoryManager(self)
        
        # [CENTRALIZED] Create the ONE and ONLY Media Controller here
        preview_panel = self.center_panel.media_preview
        self.media_controller = MediaController(preview_panel.player, preview_panel.video_widget)
        
        self.annot_manager = AnnotationManager(self)
        self.nav_manager = NavigationManager(self, self.media_controller)
        self.loc_manager = LocalizationManager(self, self.media_controller)
        
        # Description Mode Controllers
        self.desc_nav_manager = DescNavigationManager(self, self.media_controller)
        self.desc_annot_manager = DescAnnotationManager(self)
        
        # Dense Description Controller
        self.dense_manager = DenseManager(self, self.media_controller)
        self.inference_manager = InferenceManager(self)
        self.train_manager = TrainManager(self)

        # --- Local UI state (icons, etc.) ---
        bright_blue = QColor("#00BFFF")
        self.done_icon = create_checkmark_icon(bright_blue)
        self.empty_icon = QIcon()

        # --- Setup ---
        self.connect_signals()
        self.load_stylesheet()
        
        self.setup_dynamic_ui()
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

    def show_workspace(self):
        """Switch to the Media Player (Index 1 in central stack)."""
        self.center_stack.setCurrentIndex(1)
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

    # ---------------------------------------------------------------------
    # Global Media Control
    # ---------------------------------------------------------------------
    def stop_all_players(self):
        """ Stops the single unified player and clears sources. """
        self.media_controller.stop()

    def reset_all_managers(self):
        """ Clears all mode-specific UIs and returns to Welcome screen. """
        self.annot_manager.reset_ui()
        self.loc_manager.reset_ui()
        self.desc_nav_manager.reset_ui()
        self.dense_manager.reset_ui()
        
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

    # Welcome screen
    def _safe_import_annotations(self): self.router.import_annotations()
    def _safe_create_project(self): self.router.create_new_project_flow()

    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # Welcome screen
        self.welcome_widget.import_btn.clicked.connect(self._safe_import_annotations)
        self.welcome_widget.create_btn.clicked.connect(self._safe_create_project)

        # --- COMPONENT REFS ---
        left_panel = self.left_panel
        center_panel = self.center_panel
        
        # --- Left panel (Unified) ---
        left_panel.addVideoRequested.connect(self._dispatch_add_video)
        left_panel.clear_btn.clicked.connect(self._dispatch_clear_workspace)
        left_panel.request_remove_item.connect(self._on_remove_item_requested)
        left_panel.tree.selectionModel().currentChanged.connect(self._on_tree_selection_changed)
        left_panel.filter_combo.currentIndexChanged.connect(self._dispatch_filter_change)

        # --- Center panel (Unified Playback) ---
        center_panel.playback.playPauseRequested.connect(self._dispatch_play_pause)
        center_panel.playback.seekRelativeRequested.connect(self._dispatch_seek)
        center_panel.playback.stopRequested.connect(self.stop_all_players)
        center_panel.playback.playbackRateRequested.connect(center_panel.media_preview.set_playback_rate)
        
        # Navigation signals from the unified bar
        center_panel.playback.nextPrevClipRequested.connect(self._dispatch_next_prev_clip)
        center_panel.playback.nextPrevAnnotRequested.connect(self._dispatch_next_prev_annot)
        
        # --- Timeline ---
        center_panel.media_preview.durationChanged.connect(center_panel.timeline.set_duration)
        center_panel.media_preview.positionChanged.connect(center_panel.timeline.set_position)
        center_panel.timeline.seekRequested.connect(center_panel.media_preview.set_position)
        
        # --- Classification Editor ---
        self.classification_panel.annotation_saved.connect(lambda data: self.annot_manager.save_manual_annotation())
        self.classification_panel.smart_confirm_requested.connect(self.annot_manager.confirm_smart_annotation_as_manual)
        self.classification_panel.hand_clear_requested.connect(self.annot_manager.clear_current_manual_annotation)
        self.classification_panel.smart_clear_requested.connect(self.annot_manager.clear_current_smart_annotation)
        self.classification_panel.add_head_clicked.connect(self.annot_manager.handle_add_label_head)
        self.classification_panel.remove_head_clicked.connect(self.annot_manager.handle_remove_label_head)
        self.classification_panel.smart_infer_requested.connect(self.inference_manager.start_inference)
        self.classification_panel.confirm_infer_requested.connect(lambda res: self.annot_manager.save_manual_annotation())

        # --- Localization Editor ---
        self.loc_manager.setup_connections()

        # --- Description Editor ---
        self.desc_nav_manager.setup_connections()
        self.desc_annot_manager.setup_connections()

        # --- Dense Editor ---
        self.dense_manager.setup_connections()

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
        self.action_close.triggered.connect(self.router.close_project)
        file_menu.addAction(self.action_close)

        file_menu.addSeparator()

        self.action_save = QAction("Save Dataset", self)
        self.action_save.triggered.connect(self._dispatch_save)
        self.action_save.setEnabled(False)
        file_menu.addAction(self.action_save)

        self.action_export = QAction("Save Dataset As", self)
        self.action_export.triggered.connect(self._dispatch_export)
        self.action_export.setEnabled(False)
        file_menu.addAction(self.action_export)

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
        
        QShortcut(QKeySequence("Ctrl+S"), self).activated.connect(self._dispatch_save)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self).activated.connect(self._dispatch_export)

        QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(
            lambda: self.show_temp_msg("Settings", "Settings dialog not implemented yet.")
        )
        QShortcut(QKeySequence("Ctrl+D"), self).activated.connect(
            lambda: self.show_temp_msg("Downloader", "Dataset downloader not implemented yet.")
        )

        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self.history_manager.perform_undo)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self.history_manager.perform_redo)

        QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(self._dispatch_play_pause)
        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(lambda: self._dispatch_seek(-40))
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(lambda: self._dispatch_seek(40))
        QShortcut(QKeySequence("Ctrl+Left"), self).activated.connect(lambda: self._dispatch_seek(-1000))
        QShortcut(QKeySequence("Ctrl+Right"), self).activated.connect(lambda: self._dispatch_seek(1000))
        QShortcut(QKeySequence("Ctrl+Shift+Left"), self).activated.connect(lambda: self._dispatch_seek(-5000))
        QShortcut(QKeySequence("Ctrl+Shift+Right"), self).activated.connect(lambda: self._dispatch_seek(5000))

        QShortcut(QKeySequence("A"), self).activated.connect(self._dispatch_add_annotation)
        QShortcut(QKeySequence("S"), self).activated.connect(
            lambda: self.show_temp_msg("Info", "Select an event and edit time via right-click.")
        )

    # ---------------------------------------------------------------------
    # Mode-aware dispatchers
    # ---------------------------------------------------------------------
    def _get_active_mode_index(self) -> int:
        return self.right_tabs.currentIndex()

    def _is_cls_mode(self) -> bool: return self._get_active_mode_index() == 0
    def _is_loc_mode(self) -> bool: return self._get_active_mode_index() == 1
    def _is_desc_mode(self) -> bool: return self._get_active_mode_index() == 2
    def _is_dense_mode(self) -> bool: return self._get_active_mode_index() == 3

    def _dispatch_add_video(self):
        if self._is_loc_mode(): self.loc_manager._on_add_video_clicked()
        elif self._is_desc_mode(): self.desc_nav_manager.add_items_via_dialog()
        elif self._is_dense_mode(): self.dense_manager._on_add_video_clicked()
        else: self.nav_manager.add_items_via_dialog()

    def _dispatch_clear_workspace(self):
        if self._is_desc_mode(): self._on_desc_clear_clicked()
        elif self._is_dense_mode(): self.dense_manager._on_clear_all_clicked()
        else: self._on_class_clear_clicked()

    def _dispatch_filter_change(self, index):
        if self._is_loc_mode(): self.loc_manager._apply_clip_filter(index)
        elif self._is_desc_mode(): self.desc_nav_manager.apply_action_filter()
        elif self._is_dense_mode(): self.dense_manager._apply_clip_filter(index)
        else: self.nav_manager.apply_action_filter()

    def _on_tree_selection_changed(self, current: QModelIndex, previous: QModelIndex):
        if current.isValid():
            # [CENTRALIZED] Enable all editors now that a clip is selected
            self.classification_panel.manual_box.setEnabled(True)
            self.localization_panel.setEnabled(True)
            self.description_panel.setEnabled(True)
            self.dense_panel.setEnabled(True)
            
            # 1. Handle Branch (Parent) vs Leaf (Video)
            # If the user clicks a parent (e.g. Action Name), auto-select its first child (the video)
            if self.tree_model.rowCount(current) > 0:
                first_child = self.tree_model.index(0, 0, current)
                if first_child.isValid():
                    # This will trigger selectionChanged again for the child
                    self.left_panel.tree.setCurrentIndex(first_child)
                    return

            # 2. Mode-aware Dispatching (Avoid duplicate loading)
            if self._is_loc_mode():
                self.loc_manager.on_clip_selected(current, previous)
            elif self._is_desc_mode():
                self.desc_nav_manager.on_item_selected(current, previous)
            elif self._is_dense_mode():
                self.dense_manager._on_clip_selected(current, previous)
            else:
                self.nav_manager.on_item_selected(current, previous)
        else:
            # Disable editors if no clip is selected
            self.classification_panel.manual_box.setEnabled(False)
            self.localization_panel.setEnabled(False)
            self.description_panel.setEnabled(False)
            self.dense_panel.setEnabled(False)

    def _on_remove_item_requested(self, index: QModelIndex):
        if self._is_dense_mode(): self.dense_manager.remove_single_item(index)
        else: self.nav_manager.remove_single_action_item(index)

    def _dispatch_save(self) -> None:
        if self._is_loc_mode(): self.router.loc_fm.overwrite_json()
        elif self._is_desc_mode():
            self.desc_annot_manager.save_current_annotation()
            self.router.desc_fm.save_json() 
        elif self._is_dense_mode(): self.router.dense_fm.overwrite_json()
        else: self.router.class_fm.save_json()

    def _dispatch_export(self) -> None:
        if self._is_loc_mode(): self.router.loc_fm.export_json()
        elif self._is_desc_mode(): self.router.desc_fm.export_json()
        elif self._is_dense_mode(): self.router.dense_fm.export_json()
        else: self.router.class_fm.export_json()

    def _dispatch_play_pause(self) -> None:
        # All managers now use the same media controller roughly
        self.nav_manager.media_controller.toggle_play_pause()

    def _dispatch_seek(self, delta_ms: int) -> None:
        # Use our unified media_controller for seeking if available
        self.nav_manager.media_controller.seek_relative(delta_ms)

    def _dispatch_next_prev_clip(self, step: int):
        if self._is_loc_mode(): self.loc_manager._navigate_clip(step)
        elif self._is_desc_mode(): 
            if step > 0: self.desc_nav_manager.nav_next_clip()
            else: self.desc_nav_manager.nav_prev_clip()
        elif self._is_dense_mode(): self.dense_manager._navigate_clip(step)
        else:
            if step > 0: self.nav_manager.nav_next_clip()
            else: self.nav_manager.nav_prev_clip()

    def _dispatch_next_prev_annot(self, step: int):
        if self._is_loc_mode(): self.loc_manager._navigate_annotation(step)
        elif self._is_dense_mode(): self.dense_manager._navigate_annotation(step)

    def _dispatch_add_annotation(self) -> None:
        if self._is_loc_mode():
            head = self.loc_manager.current_head
            if not head: return
            self.loc_manager._on_label_add_req(head)
        elif self._is_desc_mode(): self.desc_annot_manager.save_current_annotation()
        elif self._is_dense_mode(): self.dense_manager.right_panel.input_widget._on_submit()
        else: self.annot_manager.save_manual_annotation()

    # ---------------------------------------------------------------------
    # UI Helpers
    # ---------------------------------------------------------------------
    def _on_class_clear_clicked(self) -> None:
        if not self.model.json_loaded: return
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.stop_all_players()
            self.router.class_fm._clear_workspace(full_reset=True)

    def _on_desc_clear_clicked(self) -> None:
        if not self.model.json_loaded: return
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear description workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.stop_all_players()
            self.router.desc_fm._clear_workspace(full_reset=True)

    def prepare_new_project_ui(self) -> None:
        self.set_project_ui_enabled(True)
        self.classification_panel.task_label.setText(f"Task: {self.model.current_task_name}")
        self.show_temp_msg("New Project Created", "Classification ready.")

    def prepare_new_localization_ui(self) -> None:
        self.set_project_ui_enabled(True)
        self.show_temp_msg("New Project Created", "Localization ready.")

    def prepare_new_description_ui(self) -> None:
        self.set_project_ui_enabled(True)
        self.show_temp_msg("New Project Created", "Description ready.")
    
    def prepare_new_dense_ui(self) -> None:
        self.set_project_ui_enabled(True)
        self.show_temp_msg("New Project Created", "Dense Description ready.")

    def load_stylesheet(self) -> None:
        style_path = resource_path(os.path.join("style", "style.qss"))
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception as exc: print(f"Style error: {exc}")

    def check_and_close_current_project(self) -> bool:
        if not self.model.json_loaded: return True
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Close Project")
        msg_box.setText("Continue will clear the current workspace. Continue?")
        if self.model.is_data_dirty: msg_box.setInformativeText("Unsaved changes present.")
        btn_yes = msg_box.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        msg_box.addButton("No", QMessageBox.ButtonRole.RejectRole)
        msg_box.exec()
        if msg_box.clickedButton() == btn_yes: self.stop_all_players()
        return msg_box.clickedButton() == btn_yes

    def closeEvent(self, event) -> None:
        if not self.model.is_data_dirty or not self.model.json_loaded:
            self.stop_all_players()
            event.accept()
            return
        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Annotations")
        msg.setText("Do you want to save before quitting?")
        save_btn = msg.addButton("Save & Exit", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("Discard & Exit", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()
        if msg.clickedButton() == save_btn:
            self._dispatch_save()
            self.stop_all_players()
            event.accept()
        elif msg.clickedButton() == discard_btn:
            self.stop_all_players()
            event.accept()
        else: event.ignore()

    def update_save_export_button_state(self) -> None:
        has_data = self.model.json_loaded # Simple heuristic for now
        can_export = self.model.json_loaded
        can_save = can_export and (self.model.current_json_path is not None) and self.model.is_data_dirty
        self.action_save.setEnabled(can_save)
        self.action_export.setEnabled(can_export)
        self.action_undo.setEnabled(len(self.model.undo_stack) > 0)
        self.action_redo.setEnabled(len(self.model.redo_stack) > 0)

    def show_temp_msg(self, title: str, msg: str, duration: int = 1500, **kwargs) -> None:
        one_line = " ".join(str(msg).splitlines()).strip()
        self.statusBar().showMessage(f"{title} — {one_line}" if title else one_line, duration)

    def get_current_action_path(self):
        tree_view = self.left_panel.tree
        idx = tree_view.selectionModel().currentIndex()
        if not idx.isValid(): return None
        if idx.parent().isValid(): return idx.parent().data(ProjectTreeModel.FilePathRole)
        return idx.data(ProjectTreeModel.FilePathRole)

    def sync_batch_inference_dropdowns(self) -> None:
        ed = self.classification_panel
        if not hasattr(ed, 'update_action_list'): return
        sorted_list = sorted(self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", "")))
        action_names = [d["name"] for d in sorted_list]
        ed.update_action_list(action_names)

    def populate_action_tree(self) -> None:
        self.tree_model.clear()
        self.model.action_item_map.clear()
        sorted_list = sorted(self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", "")))
        self.sync_batch_inference_dropdowns()
        for data in sorted_list:
            item = self.tree_model.add_entry(name=data["name"], path=data["path"], source_files=data.get("source_files"))
            self.model.action_item_map[data["path"]] = item
            self.update_action_item_status(data["path"])
        self._dispatch_filter_change(self.left_panel.filter_combo.currentIndex())
        tree = self.left_panel.tree
        if self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid(): tree.setCurrentIndex(first_index)

    def update_action_item_status(self, action_path: str) -> None:
        item: QStandardItem = self.model.action_item_map.get(action_path)
        if not item: return
        is_done = False # Mode-specific logic here...
        if self._is_loc_mode(): is_done = action_path in self.model.localization_events
        elif self._is_desc_mode(): 
            # Check captions
            for d in self.model.action_item_data:
                if d.get("path") == action_path:
                    if any(c.get("text", "").strip() for c in d.get("captions", [])): is_done = True
                    break
        elif self._is_dense_mode(): is_done = action_path in self.model.dense_description_events
        else: is_done = action_path in self.model.manual_annotations
        item.setIcon(self.done_icon if is_done else self.empty_icon)

    def setup_dynamic_ui(self) -> None:
        ed = self.classification_panel
        ed.setup_dynamic_labels(self.model.label_definitions)
        ed.task_label.setText(f"Task: {self.model.current_task_name}")
        self._connect_dynamic_type_buttons()

    def _connect_dynamic_type_buttons(self) -> None:
        ed = self.classification_panel
        for head, group in ed.label_groups.items():
            try: group.add_btn.clicked.disconnect()
            except: pass
            group.add_btn.clicked.connect(lambda _, h=head: self.annot_manager.add_custom_type(h))
            group.remove_label_signal.connect(lambda lbl, h=head: self.annot_manager.remove_custom_type(h, lbl))
            group.value_changed.connect(lambda h, v: self.annot_manager.handle_ui_selection_change(h, v))

    def refresh_ui_after_undo_redo(self, action_path: str) -> None:
        if not action_path:
            self._dispatch_filter_change(self.left_panel.filter_combo.currentIndex())
            self.update_save_export_button_state()
            return
        self.update_action_item_status(action_path)
        self._dispatch_filter_change(self.left_panel.filter_combo.currentIndex())
        item = self.model.action_item_map.get(action_path)
        if item:
            idx = item.index()
            self.left_panel.tree.setCurrentIndex(idx)
        if self._is_loc_mode(): self.loc_manager._display_events_for_item(action_path)
        elif self._is_desc_mode(): self.desc_nav_manager.on_item_selected(item.index(), None)
        elif self._is_dense_mode(): self.dense_manager._display_events_for_item(action_path)
        else: self.annot_manager.display_manual_annotation(action_path)
        self.update_save_export_button_state()