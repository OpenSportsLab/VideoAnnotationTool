import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, QModelIndex, pyqtSignal
from PyQt6.QtGui import QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import QAbstractItemView, QMenu, QWidget

from utils import resource_path


class DatasetExplorerTreeModel(QStandardItemModel):
    """
    Internal tree model used by DatasetExplorerPanel.
    """

    FilePathRole = Qt.ItemDataRole.UserRole

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(1)

    def add_entry(self, name: str, path: str, source_files: list = None, icon=None) -> QStandardItem:
        item = QStandardItem(name)
        item.setEditable(False)
        item.setData(path, self.FilePathRole)

        if icon:
            item.setIcon(icon)

        if source_files and len(source_files) > 1:
            for src in source_files:
                child = QStandardItem(os.path.basename(src))
                child.setEditable(False)
                child.setData(src, self.FilePathRole)
                item.appendRow(child)

        self.appendRow(item)
        return item


class DatasetExplorerPanel(QWidget):
    """
    Dataset Explorer view backed by a Qt Designer .ui file.
    """

    removeItemRequested = pyqtSignal(QModelIndex)
    addDataRequested = pyqtSignal()

    def __init__(
        self,
        tree_title="Project Items",
        filter_items=None,
        clear_text="Clear All",
        enable_context_menu=True,
        parent=None,
    ):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "common", "dataset_explorer_panel", "dataset_explorer_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DatasetExplorerPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.tree_model = DatasetExplorerTreeModel(self)
        self.tree.setModel(self.tree_model)

        self._configure_widgets(tree_title, filter_items, clear_text)
        self.btn_add_data.clicked.connect(self.addDataRequested.emit)
        self._set_context_menu_enabled(enable_context_menu)

    def _configure_widgets(self, tree_title, filter_items, clear_text):
        self.lbl_title.setText(tree_title)
        self.lbl_title.setProperty("class", "panel_header_lbl")

        self.clear_btn.setText(clear_text)
        self.clear_btn.setObjectName("panel_clear_btn")

        self.filter_combo.clear()
        if filter_items:
            self.filter_combo.addItems(filter_items)
        self.bottomLayout.setStretch(1, 1)

        self.tree.setHeaderHidden(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

    def _set_context_menu_enabled(self, enabled: bool):
        try:
            self.tree.customContextMenuRequested.disconnect(self._show_context_menu)
        except TypeError:
            pass

        if enabled:
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            self.tree.customContextMenuRequested.connect(self._show_context_menu)
        else:
            self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

    def _show_context_menu(self, pos):
        index = self.tree.indexAt(pos)
        if not index.isValid():
            return

        menu = QMenu(self.tree)
        remove_action = menu.addAction("Remove Item")
        selected = menu.exec(self.tree.mapToGlobal(pos))
        if selected == remove_action:
            self.removeItemRequested.emit(index)
