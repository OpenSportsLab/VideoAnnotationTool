import os

from PyQt6.QtCore import Qt, QTimer, QModelIndex, QUrl
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QShortcut, QStandardItem
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QMainWindow, QMessageBox,QSizePolicy

from controllers.classification.class_annotation_manager import AnnotationManager
from controllers.classification.class_navigation_manager import NavigationManager
from controllers.history_manager import HistoryManager
from controllers.localization.localization_manager import LocalizationManager
# Import Description Managers
from controllers.description.desc_navigation_manager import DescNavigationManager
from controllers.description.desc_annotation_manager import DescAnnotationManager
# [NEW] Import Dense Description Manager
from controllers.dense_description.dense_manager import DenseManager

from controllers.router import AppRouter
from models import AppStateModel

from ui.common.main_window import MainWindowUI
from models.project_tree import ProjectTreeModel
from utils import create_checkmark_icon, natural_sort_key, resource_path


class ActionClassifierApp(QMainWindow):
    """Main application window for annotation + localization + description + dense workflows."""

    FILTER_ALL = 0
    FILTER_DONE = 1
    FILTER_NOT_DONE = 2

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("SoccerNet Pro Analysis Tool")
        self.setGeometry(100, 100, 600, 400)

        # --- MVC wiring ---
        self.ui = MainWindowUI()
        self.setCentralWidget(self.ui)
        self.model = AppStateModel()

        # Instantiate the Project Tree Model
        self.tree_model = ProjectTreeModel(self)
        
        # Bind the model to Views
        self.ui.classification_ui.left_panel.tree.setModel(self.tree_model)
        self.ui.localization_ui.left_panel.tree.setModel(self.tree_model)
        self.ui.description_ui.left_panel.tree.setModel(self.tree_model)
        # [NEW] Bind to Dense Description View
        self.ui.dense_description_ui.left_panel.tree.setModel(self.tree_model)

        # --- Controllers ---
        self.router = AppRouter(self)
        self.history_manager = HistoryManager(self)
        self.annot_manager = AnnotationManager(self)
        self.nav_manager = NavigationManager(self)
        self.loc_manager = LocalizationManager(self)
        
        # Description Mode Controllers
        self.desc_nav_manager = DescNavigationManager(self)
        self.desc_annot_manager = DescAnnotationManager(self)
        
        # [NEW] Dense Description Controller
        self.dense_manager = DenseManager(self)

        # --- Local UI state (icons, etc.) ---
        bright_blue = QColor("#00BFFF")
        self.done_icon = create_checkmark_icon(bright_blue)
        self.empty_icon = QIcon()

        # --- Setup ---
        self.connect_signals()
        self.load_stylesheet()
        
        # Default state: classification right panel is disabled until project loads
        self.ui.classification_ui.right_panel.manual_box.setEnabled(False)
        
        self.setup_dynamic_ui()
        self._setup_shortcuts()

        self.ui.stack_layout.currentChanged.connect(self._adjust_window_size)
        # Start at welcome screen
        self.ui.show_welcome_view()
        self._adjust_window_size(0)

    # ---------------------------------------------------------------------
    # Global Media Control to Prevent Freezing/Ghost Frames
    # ---------------------------------------------------------------------
    def stop_all_players(self):
        """
        Forcefully stops ALL media players in ALL modes and clears their sources.
        This prevents the 'stuck frame' or 'black screen' issue when switching 
        projects or modes.
        """
        # 1. Classification
        if hasattr(self.nav_manager, 'media_controller'):
            self.nav_manager.media_controller.stop()

        # 2. Localization
        if hasattr(self.loc_manager, 'media_controller'):
            self.loc_manager.media_controller.stop()

        # 3. Description
        if hasattr(self.desc_nav_manager, 'media_controller'):
            self.desc_nav_manager.media_controller.stop()
            
        # 4. [NEW] Dense Description
        if hasattr(self.dense_manager, 'media_controller'):
            self.dense_manager.media_controller.stop()

    def _adjust_window_size(self, index: int) -> None:
        """
        Dynamically exchange the size of windows
        """
        for i in range(self.ui.stack_layout.count()):
            widget = self.ui.stack_layout.widget(i)
            if not widget:
                continue
            
            if i == index:
                widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            else:
                widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self.ui.updateGeometry()

        if index == 0:
            if self.isMaximized():
                self.showNormal()
                
            self.setMinimumSize(0, 0) 
            
            self.resize(600, 400)     
        else:
            self.setMinimumSize(1000, 700) 
            
            self.resize(1400, 900)

    def _safe_import_annotations(self):
        """Wrapper to ensure players are stopped before loading a new project."""
        self.stop_all_players()
        self.router.import_annotations()

    def _safe_create_project(self):
        """Wrapper to ensure players are stopped before creating a new project."""
        self.stop_all_players()
        self.router.create_new_project_flow()

    # ---------------------------------------------------------------------
    # Wiring
    # ---------------------------------------------------------------------
    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # Welcome screen
        self.ui.welcome_widget.import_btn.clicked.connect(self._safe_import_annotations)
        self.ui.welcome_widget.create_btn.clicked.connect(self._safe_create_project)

        # --- Classification - Left panel ---
        cls_left = self.ui.classification_ui.left_panel
        cls_controls = cls_left.project_controls
        
        cls_controls.createRequested.connect(self._safe_create_project)
        cls_controls.loadRequested.connect(self._safe_import_annotations)
        
        cls_controls.addVideoRequested.connect(self.nav_manager.add_items_via_dialog)
        cls_controls.closeRequested.connect(self.router.close_project)
        cls_controls.saveRequested.connect(self.router.class_fm.save_json)
        cls_controls.exportRequested.connect(self.router.class_fm.export_json)

        cls_left.clear_btn.clicked.connect(self._on_class_clear_clicked)
        cls_left.request_remove_item.connect(self._on_remove_item_requested)
        cls_left.tree.selectionModel().currentChanged.connect(self._on_tree_selection_changed)
        cls_left.filter_combo.currentIndexChanged.connect(self.nav_manager.apply_action_filter)

        # --- Classification - Center panel ---
        cls_center = self.ui.classification_ui.center_panel
        cls_center.play_btn.clicked.connect(self.nav_manager.play_video)
        cls_center.prev_action.clicked.connect(self.nav_manager.nav_prev_action)
        cls_center.prev_clip.clicked.connect(self.nav_manager.nav_prev_clip)
        cls_center.next_clip.clicked.connect(self.nav_manager.nav_next_clip)
        cls_center.next_action.clicked.connect(self.nav_manager.nav_next_action)

        # --- Classification - Right panel ---
        cls_right = self.ui.classification_ui.right_panel
        cls_right.confirm_btn.clicked.connect(self.annot_manager.save_manual_annotation)
        cls_right.clear_sel_btn.clicked.connect(self.annot_manager.clear_current_manual_annotation)
        cls_right.add_head_clicked.connect(self.annot_manager.handle_add_label_head)
        cls_right.remove_head_clicked.connect(self.annot_manager.handle_remove_label_head)

        # Undo/redo for Class/Loc
        cls_right.undo_btn.clicked.connect(self.history_manager.perform_undo)
        cls_right.redo_btn.clicked.connect(self.history_manager.perform_redo)
        self.ui.localization_ui.right_panel.undo_btn.clicked.connect(self.history_manager.perform_undo)
        self.ui.localization_ui.right_panel.redo_btn.clicked.connect(self.history_manager.perform_redo)

        # --- Localization panel ---
        loc_controls = self.ui.localization_ui.left_panel.project_controls
        loc_controls.createRequested.connect(self._safe_create_project)
        loc_controls.loadRequested.connect(self._safe_import_annotations) 
        loc_controls.closeRequested.connect(self.router.close_project)

        self.loc_manager.setup_connections()

        # --- Description Panel Wiring ---
        desc_left = self.ui.description_ui.left_panel
        desc_controls = desc_left.project_controls
        
        desc_controls.createRequested.connect(self._safe_create_project)
        desc_controls.loadRequested.connect(self._safe_import_annotations) 
        desc_controls.closeRequested.connect(self.router.close_project)
        
        desc_controls.addVideoRequested.connect(self.desc_nav_manager.add_items_via_dialog)
        desc_controls.saveRequested.connect(self.router.desc_fm.save_json)
        desc_controls.exportRequested.connect(self.router.desc_fm.export_json)

        desc_left.filter_combo.currentIndexChanged.connect(self.desc_nav_manager.apply_action_filter)
        desc_left.clear_btn.clicked.connect(self._on_desc_clear_clicked)

        self.desc_nav_manager.setup_connections()
        self.desc_annot_manager.setup_connections()

        desc_right = self.ui.description_ui.right_panel
        desc_right.undo_btn.clicked.connect(self.history_manager.perform_undo)
        desc_right.redo_btn.clicked.connect(self.history_manager.perform_redo)
        
        # --- [NEW] Dense Description Panel Wiring ---
        dense_left = self.ui.dense_description_ui.left_panel
        dense_controls = dense_left.project_controls
        
        dense_controls.createRequested.connect(self._safe_create_project)
        dense_controls.loadRequested.connect(self._safe_import_annotations) 
        dense_controls.closeRequested.connect(self.router.close_project)
        
        dense_controls.addVideoRequested.connect(self.dense_manager._on_add_video_clicked)
        dense_controls.saveRequested.connect(self.router.dense_fm.overwrite_json)
        dense_controls.exportRequested.connect(self.router.dense_fm.export_json)
        
        dense_left.filter_combo.currentIndexChanged.connect(self.dense_manager._apply_clip_filter)
        dense_left.clear_btn.clicked.connect(self.dense_manager._on_clear_all_clicked)
        dense_left.request_remove_item.connect(self.dense_manager.remove_single_item)
        
        # Initialize connections for Dense logic
        self.dense_manager.setup_connections()
        
        # Connect Undo/Redo for Dense Right Panel
        dense_right = self.ui.dense_description_ui.right_panel
        dense_right.undo_btn.clicked.connect(self.history_manager.perform_undo)
        dense_right.redo_btn.clicked.connect(self.history_manager.perform_redo)

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
    # MV Adapter Methods
    # ---------------------------------------------------------------------
    def _on_tree_selection_changed(self, current: QModelIndex, previous: QModelIndex):
        # Description and Dense handle their own signals in their respective managers
        if self._is_desc_mode() or self._is_dense_mode():
            return

        if current.isValid():
            self.nav_manager.on_item_selected(current, previous)

    def _on_remove_item_requested(self, index: QModelIndex):
        """Handle context menu remove request via Model Index."""
        if index.isValid():
            self.nav_manager.remove_single_action_item(index)

    # ---------------------------------------------------------------------
    # Mode-aware dispatchers
    # ---------------------------------------------------------------------
    def _is_loc_mode(self) -> bool:
        return self.ui.stack_layout.currentWidget() == self.ui.localization_ui

    def _is_desc_mode(self) -> bool:
        """Helper to check if current view is Global Description."""
        if self.ui.stack_layout.currentWidget() == self.ui.description_ui:
            return True
        task = str(self.model.current_task_name).lower()
        return ("caption" in task or "description" in task) and "dense" not in task
    
    def _is_dense_mode(self) -> bool:
        """[NEW] Helper to check if current view is Dense Description."""
        return self.ui.stack_layout.currentWidget() == self.ui.dense_description_ui

    def _dispatch_save(self) -> None:
        if self._is_loc_mode():
            self.router.loc_fm.overwrite_json()
        elif self._is_desc_mode():
            self.desc_annot_manager.save_current_annotation()
            self.router.desc_fm.save_json() 
        elif self._is_dense_mode():
            # [NEW] Save Dense Description
            self.router.dense_fm.overwrite_json()
        else:
            self.router.class_fm.save_json()

    def _dispatch_export(self) -> None:
        if self._is_loc_mode():
            self.router.loc_fm.export_json()
        elif self._is_desc_mode():
            self.router.desc_fm.export_json()
        elif self._is_dense_mode():
            # [NEW] Export Dense Description
            self.router.dense_fm.export_json()
        else:
            self.router.class_fm.export_json()

    def _dispatch_play_pause(self) -> None:
        if self._is_loc_mode():
            self.loc_manager.media_controller.toggle_play_pause()
        elif self._is_desc_mode():
            self.desc_nav_manager.media_controller.toggle_play_pause()
        elif self._is_dense_mode():
            # [NEW] Forward to Dense Controller
            self.dense_manager.media_controller.toggle_play_pause()
        else:
            self.nav_manager.media_controller.toggle_play_pause()

    def _dispatch_seek(self, delta_ms: int) -> None:
        player = None
        if self._is_loc_mode():
            player = self.loc_manager.center_panel.media_preview.player
        elif self._is_desc_mode():
            player = self.ui.description_ui.center_panel.player
        elif self._is_dense_mode():
            # [NEW] Get player from Dense View (shared with LocCenterPanel structure)
            player = self.dense_manager.center_panel.media_preview.player
        else:
            player = self.ui.classification_ui.center_panel.single_view_widget.player

        if player:
            player.setPosition(max(0, player.position() + delta_ms))

    def _dispatch_add_annotation(self) -> None:
        """Handles the 'A' shortcut based on mode."""
        if self._is_loc_mode():
            current_head = self.loc_manager.current_head
            if not current_head:
                self.show_temp_msg("Warning", "No head/category selected.", icon=QMessageBox.Icon.Warning)
                return
            self.loc_manager._on_label_add_req(current_head)
        elif self._is_desc_mode():
            self.desc_annot_manager.save_current_annotation()
        elif self._is_dense_mode():
            # [NEW] Trigger description submission from Input Widget
            self.dense_manager.right_panel.input_widget._on_submit()
        else:
            self.annot_manager.save_manual_annotation()

    # ---------------------------------------------------------------------
    # UI actions / helpers
    # ---------------------------------------------------------------------
    def _on_class_clear_clicked(self) -> None:
        if not self.model.json_loaded and not self.model.action_item_data:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.stop_all_players()
            self.router.class_fm._clear_workspace(full_reset=True)

    def _on_desc_clear_clicked(self) -> None:
        if not self.model.json_loaded and not self.model.action_item_data:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear description workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.stop_all_players()
            self.router.desc_fm._clear_workspace(full_reset=True)

    def prepare_new_project_ui(self) -> None:
        self.ui.classification_ui.right_panel.manual_box.setEnabled(True)
        self.ui.classification_ui.right_panel.task_label.setText(f"Task: {self.model.current_task_name}")
        self.show_temp_msg("New Project Created", "Classification Workspace ready.")

    def prepare_new_localization_ui(self) -> None:
        self.ui.localization_ui.right_panel.setEnabled(True)
        self.statusBar().showMessage("New Project Created — Localization Workspace ready.", 1500)

    def prepare_new_description_ui(self) -> None:
        self.ui.description_ui.right_panel.setEnabled(True)
        self.statusBar().showMessage("New Project Created — Description Workspace ready.", 1500)
    
    def prepare_new_dense_ui(self) -> None:
        """[NEW] Unlocks the Dense Description UI components."""
        self.ui.dense_description_ui.right_panel.setEnabled(True)
        self.statusBar().showMessage("New Project Created — Dense Description Workspace ready.", 1500)

    def load_stylesheet(self) -> None:
        style_path = resource_path(os.path.join("style", "style.qss"))
        try:
            with open(style_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception as exc:
            print(f"Style error: {exc}")

    def check_and_close_current_project(self) -> bool:
        if not self.model.json_loaded:
            return True

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Close Project")
        msg_box.setText("Opening a new project or closing will clear the current workspace. Continue?")
        msg_box.setIcon(QMessageBox.Icon.Warning)

        if self.model.is_data_dirty:
            msg_box.setInformativeText("You have unsaved changes in the current project.")

        btn_yes = msg_box.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        btn_no = msg_box.addButton("No", QMessageBox.ButtonRole.RejectRole)
        msg_box.setDefaultButton(btn_no)
        msg_box.exec()
        
        if msg_box.clickedButton() == btn_yes:
            self.stop_all_players()

        return msg_box.clickedButton() == btn_yes

    def closeEvent(self, event) -> None:
        is_loc = self._is_loc_mode()
        is_desc = self._is_desc_mode() 
        is_dense = self._is_dense_mode() # [NEW]

        has_data = False
        if is_loc:
            has_data = bool(self.model.localization_events)
        elif is_desc:
            has_data = self.model.json_loaded 
        elif is_dense:
            # [NEW] Check dense data
            has_data = bool(self.model.dense_description_events)
        else:
            has_data = bool(self.model.manual_annotations)

        can_export = self.model.json_loaded and has_data

        if not self.model.is_data_dirty or not can_export:
            self.stop_all_players()
            event.accept()
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Unsaved Annotations")
        msg.setText("Do you want to save your annotations before quitting?")
        msg.setIcon(QMessageBox.Icon.Question)

        save_btn = msg.addButton("Save & Exit", QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg.addButton("Discard & Exit", QMessageBox.ButtonRole.DestructiveRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)

        msg.setDefaultButton(save_btn)
        msg.exec()

        if msg.clickedButton() == save_btn:
            ok = False
            if is_loc:
                ok = self.router.loc_fm.overwrite_json()
            elif is_desc:
                self.desc_annot_manager.save_current_annotation()
                ok = self.router.desc_fm.save_json()
            elif is_dense:
                # [NEW] Save Dense
                ok = self.router.dense_fm.overwrite_json()
            else:
                ok = self.router.class_fm.save_json()
            
            if ok:
                self.stop_all_players()
                event.accept() 
            else:
                event.ignore()
        elif msg.clickedButton() == discard_btn:
            self.stop_all_players()
            event.accept()
        else:
            event.ignore()

    def update_save_export_button_state(self) -> None:
        is_loc = self._is_loc_mode()
        is_desc = self._is_desc_mode()
        is_dense = self._is_dense_mode() # [NEW]

        has_data = False
        if is_loc:
            has_data = bool(self.model.localization_events)
        elif is_desc:
            has_data = self.model.json_loaded
        elif is_dense:
            # [NEW]
            has_data = bool(self.model.dense_description_events)
        else:
            has_data = bool(self.model.manual_annotations)

        can_export = self.model.json_loaded and has_data
        can_save = can_export and (self.model.current_json_path is not None) and self.model.is_data_dirty

        # Update controls across all mode panels
        for panel in [self.ui.classification_ui, self.ui.localization_ui, 
                      self.ui.description_ui, self.ui.dense_description_ui]:
            panel.left_panel.project_controls.btn_save.setEnabled(can_save)
            panel.left_panel.project_controls.btn_export.setEnabled(can_export)

        can_undo = len(self.model.undo_stack) > 0
        can_redo = len(self.model.redo_stack) > 0

        self.ui.classification_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.classification_ui.right_panel.redo_btn.setEnabled(can_redo)
        self.ui.localization_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.localization_ui.right_panel.redo_btn.setEnabled(can_redo)
        self.ui.description_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.description_ui.right_panel.redo_btn.setEnabled(can_redo)
        # [NEW] Dense right panel buttons
        self.ui.dense_description_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.dense_description_ui.right_panel.redo_btn.setEnabled(can_redo)

    def show_temp_msg(self, title: str, msg: str, duration: int = 1500, **kwargs) -> None:
        one_line = " ".join(str(msg).splitlines()).strip()
        text = f"{title} — {one_line}" if title else one_line
        self.statusBar().showMessage(text, duration)

    def get_current_action_path(self):
        """Return the selected action path from the tree (top-level item path)."""
        tree_view = None
        if self._is_loc_mode():
            tree_view = self.ui.localization_ui.left_panel.tree
        elif self._is_desc_mode():
            tree_view = self.ui.description_ui.left_panel.tree
        elif self._is_dense_mode():
            tree_view = self.ui.dense_description_ui.left_panel.tree
        else:
            tree_view = self.ui.classification_ui.left_panel.tree

        idx = tree_view.selectionModel().currentIndex()
        if not idx.isValid():
            return None
        if idx.parent().isValid():
            return idx.parent().data(ProjectTreeModel.FilePathRole)
        return idx.data(ProjectTreeModel.FilePathRole)

    def populate_action_tree(self) -> None:
        """Rebuild the action tree from model data using the new ProjectTreeModel."""
        self.tree_model.clear()
        self.model.action_item_map.clear()

        sorted_list = sorted(self.model.action_item_data, key=lambda d: natural_sort_key(d.get("name", "")))
        
        for data in sorted_list:
            item = self.tree_model.add_entry(
                name=data["name"], 
                path=data["path"], 
                source_files=data.get("source_files")
            )
            self.model.action_item_map[data["path"]] = item

        for path in self.model.action_item_map.keys():
            self.update_action_item_status(path)

        # Decide which manager handles the navigation logic
        if self._is_loc_mode():
            self.loc_manager._apply_clip_filter(self.ui.localization_ui.left_panel.filter_combo.currentIndex())
        elif self._is_desc_mode():
            self.desc_nav_manager.apply_action_filter()
        elif self._is_dense_mode():
            self.dense_manager._apply_clip_filter(self.ui.dense_description_ui.left_panel.filter_combo.currentIndex())
        else:
            self.nav_manager.apply_action_filter()

        active_tree = None
        if self._is_desc_mode():
            active_tree = self.ui.description_ui.left_panel.tree
        elif not self._is_loc_mode() and not self._is_dense_mode():
            active_tree = self.ui.classification_ui.left_panel.tree

        if active_tree and self.tree_model.rowCount() > 0:
            first_index = self.tree_model.index(0, 0)
            if first_index.isValid():
                active_tree.setCurrentIndex(first_index)

   

    def update_action_item_status(self, action_path: str) -> None:
        item: QStandardItem = self.model.action_item_map.get(action_path)
        if not item:
            return

        is_done = False
        if self._is_loc_mode():
            is_done = action_path in self.model.localization_events and bool(self.model.localization_events[action_path])
        elif self._is_desc_mode():
            # Correctly identify if the action has ANY non-empty caption text
            for d in self.model.action_item_data:
                # Support both path and ID matching
                if d.get("path") == action_path or d.get("id") == action_path:
                    captions = d.get("captions", [])
                    if any(cap.get("text", "").strip() for cap in captions):
                        is_done = True
                    break

        elif self._is_dense_mode():
            is_done = action_path in self.model.dense_description_events and bool(self.model.dense_description_events[action_path])
        else:
            # Classification mode logic
            is_done = action_path in self.model.manual_annotations and bool(self.model.manual_annotations[action_path])
            
        item.setIcon(self.done_icon if is_done else self.empty_icon)


    def setup_dynamic_ui(self) -> None:
        cls_right = self.ui.classification_ui.right_panel
        cls_right.setup_dynamic_labels(self.model.label_definitions)
        cls_right.task_label.setText(f"Task: {self.model.current_task_name}")
        self._connect_dynamic_type_buttons()

    def _connect_dynamic_type_buttons(self) -> None:
        for head, group in self.ui.classification_ui.right_panel.label_groups.items():
            try:
                group.add_btn.clicked.disconnect()
            except Exception:
                pass
            group.add_btn.clicked.connect(lambda _, h=head: self.annot_manager.add_custom_type(h))
            group.remove_label_signal.connect(lambda lbl, h=head: self.annot_manager.remove_custom_type(h, lbl))
            group.value_changed.connect(lambda h, v: self.annot_manager.handle_ui_selection_change(h, v))

    def refresh_ui_after_undo_redo(self, action_path: str) -> None:
        """
        Refreshes the UI after an Undo/Redo operation.
        Updates the tree icon, selection, and the active editor content.
        """
        if not action_path:
            return

        # 1. Update the tree icon status
        self.update_action_item_status(action_path)

        # 2. Ensure the item is selected in the active tree
        active_tree = None
        if self._is_loc_mode():
            active_tree = self.ui.localization_ui.left_panel.tree
        elif self._is_desc_mode():
            active_tree = self.ui.description_ui.left_panel.tree
        elif self._is_dense_mode():
            active_tree = self.ui.dense_description_ui.left_panel.tree
        else:
            active_tree = self.ui.classification_ui.left_panel.tree

        item: QStandardItem = self.model.action_item_map.get(action_path)
        if item and active_tree:
            idx = item.index()
            if active_tree.currentIndex() != idx:
                active_tree.setCurrentIndex(idx)

        # 3. Refresh the Right Panel Content
        if self._is_loc_mode():
            self.loc_manager._display_events_for_item(action_path)
        elif self._is_desc_mode():
            self.desc_nav_manager.on_item_selected(item.index(), None)
        elif self._is_dense_mode():
            # [NEW] Refresh Dense events display
            self.dense_manager._display_events_for_item(action_path)
        else:
            self.annot_manager.display_manual_annotation(action_path)

        self.update_save_export_button_state()
