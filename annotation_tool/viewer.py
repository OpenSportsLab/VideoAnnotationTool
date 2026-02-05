import os

from PyQt6.QtCore import Qt, QTimer, QModelIndex
from PyQt6.QtGui import QColor, QIcon, QKeySequence, QShortcut, QStandardItem
from PyQt6.QtMultimedia import QMediaPlayer
from PyQt6.QtWidgets import QMainWindow, QMessageBox

from controllers.classification.annotation_manager import AnnotationManager
from controllers.classification.navigation_manager import NavigationManager
from controllers.history_manager import HistoryManager
from controllers.localization.localization_manager import LocalizationManager
# [NEW] Import Description Managers
from controllers.description.desc_navigation_manager import DescNavigationManager
from controllers.description.desc_annotation_manager import DescAnnotationManager
from controllers.router import AppRouter
from models import AppStateModel

from ui.common.main_window import MainWindowUI
from models.project_tree import ProjectTreeModel
from utils import create_checkmark_icon, natural_sort_key, resource_path


class ActionClassifierApp(QMainWindow):
    """Main application window for annotation + localization + description workflows."""

    FILTER_ALL = 0
    FILTER_DONE = 1
    FILTER_NOT_DONE = 2

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("SoccerNet Pro Analysis Tool")
        self.setGeometry(100, 100, 1400, 900)

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

        # --- Controllers ---
        self.router = AppRouter(self)
        self.history_manager = HistoryManager(self)
        self.annot_manager = AnnotationManager(self)
        self.nav_manager = NavigationManager(self)
        self.loc_manager = LocalizationManager(self)
        
        # [NEW] Description Mode Controllers
        self.desc_nav_manager = DescNavigationManager(self)
        self.desc_annot_manager = DescAnnotationManager(self)

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

        # Start at welcome screen
        self.ui.show_welcome_view()

    # ---------------------------------------------------------------------
    # Wiring
    # ---------------------------------------------------------------------
    def connect_signals(self) -> None:
        """Connect UI signals to controller actions."""

        # Welcome screen
        self.ui.welcome_widget.import_btn.clicked.connect(self.router.import_annotations)
        self.ui.welcome_widget.create_btn.clicked.connect(self.router.create_new_project_flow)

        # --- Classification - Left panel ---
        cls_left = self.ui.classification_ui.left_panel
        cls_controls = cls_left.project_controls
        
        cls_controls.createRequested.connect(self.router.create_new_project_flow)
        cls_controls.loadRequested.connect(self.router.import_annotations)
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
        cls_center.multi_view_btn.clicked.connect(self.nav_manager.show_all_views)
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

        # Undo/redo
        cls_right.undo_btn.clicked.connect(self.history_manager.perform_undo)
        cls_right.redo_btn.clicked.connect(self.history_manager.perform_redo)
        self.ui.localization_ui.right_panel.undo_btn.clicked.connect(self.history_manager.perform_undo)
        self.ui.localization_ui.right_panel.redo_btn.clicked.connect(self.history_manager.perform_redo)

        # --- Localization panel ---
        loc_controls = self.ui.localization_ui.left_panel.project_controls
        loc_controls.createRequested.connect(self.router.create_new_project_flow)
        loc_controls.closeRequested.connect(self.router.close_project)

        self.loc_manager.setup_connections()

        # --- [NEW] Description Panel Wiring ---
        desc_left = self.ui.description_ui.left_panel
        desc_controls = desc_left.project_controls
        
        desc_controls.createRequested.connect(self.router.create_new_project_flow)
        desc_controls.loadRequested.connect(self.router.import_annotations) # Reuse Generic Router
        desc_controls.closeRequested.connect(self.router.close_project) # Reuse Generic Router
        
        # Connect Specific Managers
        desc_controls.addVideoRequested.connect(self.desc_nav_manager.add_items_via_dialog)
        desc_controls.saveRequested.connect(self.router.desc_fm.save_json)
        desc_controls.exportRequested.connect(self.router.desc_fm.export_json)

        # [NEW] Filter & Clear for Description
        desc_left.filter_combo.currentIndexChanged.connect(self.desc_nav_manager.apply_action_filter)
        desc_left.clear_btn.clicked.connect(self._on_desc_clear_clicked)

        # Connect Description Logic
        self.desc_nav_manager.setup_connections()
        self.desc_annot_manager.setup_connections()

    def _setup_shortcuts(self) -> None:
        """Register common keyboard shortcuts."""
        QShortcut(QKeySequence("Ctrl+O"), self).activated.connect(self.router.import_annotations)
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
        # Only for Classification; Description handles its own signals in DescNavigationManager
        if self._is_desc_mode():
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
        """[NEW] Helper to check if current view is Description."""
        return self.ui.stack_layout.currentWidget() == self.ui.description_ui

    def _dispatch_save(self) -> None:
        if self._is_loc_mode():
            self.router.loc_fm.overwrite_json()
        elif self._is_desc_mode():
            # [NEW] Save current editor text first
            self.desc_annot_manager.save_current_annotation()
            self.router.desc_fm.save_json() 
        else:
            self.router.class_fm.save_json()

    def _dispatch_export(self) -> None:
        if self._is_loc_mode():
            self.router.loc_fm.export_json()
        elif self._is_desc_mode():
            self.router.desc_fm.export_json()
        else:
            self.router.class_fm.export_json()

    def _dispatch_play_pause(self) -> None:
        if self._is_loc_mode():
            player = self.loc_manager.center_panel.media_preview.player
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                player.pause()
            else:
                player.play()
        elif self._is_desc_mode():
            # [NEW] Forward to Description UI
            self.ui.description_ui.center_panel.toggle_play_pause()
        else:
            player = self.ui.classification_ui.center_panel.single_view_widget.player
            if player:
                if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                    player.pause()
                else:
                    player.play()

    def _dispatch_seek(self, delta_ms: int) -> None:
        player = None
        if self._is_loc_mode():
            player = self.loc_manager.center_panel.media_preview.player
        elif self._is_desc_mode():
             # [NEW] Forward to Description UI
            player = self.ui.description_ui.center_panel.player
        else:
            player = self.ui.classification_ui.center_panel.single_view_widget.player

        if player:
            player.setPosition(max(0, player.position() + delta_ms))

    def _dispatch_add_annotation(self) -> None:
        if self._is_loc_mode():
            current_head = self.loc_manager.current_head
            if not current_head:
                self.show_temp_msg("Warning", "No head/category selected.", icon=QMessageBox.Icon.Warning)
                return
            self.loc_manager._on_label_add_req(current_head)
        elif self._is_desc_mode():
            # [NEW] Shortcut 'A' triggers save/confirm in Description mode
            self.desc_annot_manager.save_current_annotation()
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
            self.router.class_fm._clear_workspace(full_reset=True)

    def _on_desc_clear_clicked(self) -> None:
        """[NEW] Handle Clear button click for Description Mode."""
        if not self.model.json_loaded and not self.model.action_item_data:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Workspace")
        msg.setText("Clear description workspace? Unsaved changes will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.router.desc_fm._clear_workspace(full_reset=True)

    def prepare_new_project_ui(self) -> None:
        """Unlocks the Classification UI components for a fresh blank project."""
        self.ui.classification_ui.right_panel.manual_box.setEnabled(True)
        self.ui.classification_ui.right_panel.task_label.setText(f"Task: {self.model.current_task_name}")
        self.show_temp_msg("New Project Created", "Classification Workspace ready.")

    def prepare_new_localization_ui(self) -> None:
        """Unlocks the Localization UI components for a fresh blank project."""
        self.ui.localization_ui.right_panel.setEnabled(True)
        self.statusBar().showMessage("New Project Created — Localization Workspace ready.", 1500)

    def prepare_new_description_ui(self) -> None:
        """[NEW] Unlocks the Description UI components for a fresh blank project."""
        self.ui.description_ui.right_panel.setEnabled(True)
        self.statusBar().showMessage("New Project Created — Description Workspace ready.", 1500)

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

        return msg_box.clickedButton() == btn_yes

    def closeEvent(self, event) -> None:
        # Check current mode for unsaved data
        is_loc = self._is_loc_mode()
        is_desc = self._is_desc_mode() # [NEW]

        has_data = False
        if is_loc:
            has_data = bool(self.model.localization_events)
        elif is_desc:
            # Assume true if project loaded for now
            has_data = self.model.json_loaded 
        else:
            has_data = bool(self.model.manual_annotations)

        can_export = self.model.json_loaded and has_data

        if not self.model.is_data_dirty or not can_export:
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
                # Save RAM state then Disk
                self.desc_annot_manager.save_current_annotation()
                ok = self.router.desc_fm.save_json()
            else:
                ok = self.router.class_fm.save_json()
            
            event.accept() if ok else event.ignore()
        elif msg.clickedButton() == discard_btn:
            event.accept()
        else:
            event.ignore()

    def update_save_export_button_state(self) -> None:
        # Update buttons for all modes
        is_loc = self._is_loc_mode()
        is_desc = self._is_desc_mode()

        has_data = False
        if is_loc:
            has_data = bool(self.model.localization_events)
        elif is_desc:
            has_data = self.model.json_loaded
        else:
            has_data = bool(self.model.manual_annotations)

        can_export = self.model.json_loaded and has_data
        can_save = can_export and (self.model.current_json_path is not None) and self.model.is_data_dirty

        # Update Classification controls
        self.ui.classification_ui.left_panel.project_controls.btn_save.setEnabled(can_save)
        self.ui.classification_ui.left_panel.project_controls.btn_export.setEnabled(can_export)
        
        # Update Localization controls
        self.ui.localization_ui.left_panel.project_controls.btn_save.setEnabled(can_save)
        self.ui.localization_ui.left_panel.project_controls.btn_export.setEnabled(can_export)

        # [NEW] Update Description controls
        self.ui.description_ui.left_panel.project_controls.btn_save.setEnabled(can_save)
        self.ui.description_ui.left_panel.project_controls.btn_export.setEnabled(can_export)

        can_undo = len(self.model.undo_stack) > 0
        can_redo = len(self.model.redo_stack) > 0

        self.ui.classification_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.classification_ui.right_panel.redo_btn.setEnabled(can_redo)
        self.ui.localization_ui.right_panel.undo_btn.setEnabled(can_undo)
        self.ui.localization_ui.right_panel.redo_btn.setEnabled(can_redo)
        # TODO: Description Undo/Redo buttons

    def show_temp_msg(self, title: str, msg: str, duration: int = 1500, **kwargs) -> None:
        one_line = " ".join(str(msg).splitlines()).strip()
        text = f"{title} — {one_line}" if title else one_line
        self.statusBar().showMessage(text, duration)

    def get_current_action_path(self):
        """Return the selected action path from the tree (top-level item path)."""
        # Note: This currently assumes Classification tree focus. 
        # For Description mode, we might need to check which tree is focused.
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

        self.nav_manager.apply_action_filter()

        if self.tree_model.rowCount() > 0:
            first_idx = self.tree_model.index(0, 0)
            # Default to Classification tree focus for now
            tree_view = self.ui.classification_ui.left_panel.tree
            tree_view.setCurrentIndex(first_idx)
            QTimer.singleShot(200, self.nav_manager.play_video)

    def update_action_item_status(self, action_path: str) -> None:
        item: QStandardItem = self.model.action_item_map.get(action_path)
        if not item:
            return

        is_done = action_path in self.model.manual_annotations and bool(self.model.manual_annotations[action_path])
        item.setIcon(self.done_icon if is_done else self.empty_icon)

        self.nav_manager.apply_action_filter()

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
            try:
                group.remove_label_signal.disconnect()
            except Exception:
                pass
            try:
                group.value_changed.disconnect()
            except Exception:
                pass

            group.add_btn.clicked.connect(lambda _, h=head: self.annot_manager.add_custom_type(h))
            group.remove_label_signal.connect(lambda lbl, h=head: self.annot_manager.remove_custom_type(h, lbl))
            group.value_changed.connect(lambda h, v: self.annot_manager.handle_ui_selection_change(h, v))

    def refresh_ui_after_undo_redo(self, action_path: str) -> None:
        if not action_path:
            return

        self.update_action_item_status(action_path)

        item: QStandardItem = self.model.action_item_map.get(action_path)
        tree_view = self.ui.classification_ui.left_panel.tree
        
        if item:
            idx = item.index()
            if tree_view.currentIndex() != idx:
                tree_view.setCurrentIndex(idx)

        current = self.get_current_action_path()
        if current == action_path:
            self.annot_manager.display_manual_annotation(action_path)

        self.update_save_export_button_state()