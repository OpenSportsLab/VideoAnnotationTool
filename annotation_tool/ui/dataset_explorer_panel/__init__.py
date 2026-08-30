import os
import copy
import json
import re

from PyQt6 import uic
from PyQt6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QModelIndex,
    QSignalBlocker,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from utils import resource_path
from explorer_settings import DEFAULT_EXPLORER_PAGE_SIZE, normalize_explorer_page_size


def _natural_sort_text(value) -> str:
    parts = re.split(r"([0-9]+)", str(value or "").casefold())
    return "".join(part.zfill(12) if part.isdigit() else part for part in parts)


class DatasetExplorerTreeModel(QAbstractItemModel):
    """Data-backed model exposing one bounded page of samples and inputs."""

    FilePathRole = Qt.ItemDataRole.UserRole
    DataIdRole = Qt.ItemDataRole.UserRole + 1
    SortRole = Qt.ItemDataRole.UserRole + 2
    InputTypeRole = Qt.ItemDataRole.UserRole + 3
    BallPathRole = Qt.ItemDataRole.UserRole + 4

    renameRequested = pyqtSignal(str, str)
    pageChanged = pyqtSignal(int, int, int)

    DEFAULT_PAGE_SIZE = DEFAULT_EXPLORER_PAGE_SIZE

    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_entries = []
        self._projected_entries = []
        self._entry_by_id = {}
        self._children_by_id = {}
        self._projected_row_by_id = {}
        self._path_nodes = {}
        self._filter_index = 0
        self._page_number = 0
        self._page_size = self.DEFAULT_PAGE_SIZE

    def clear(self):
        self.beginResetModel()
        self._all_entries = []
        self._projected_entries = []
        self._entry_by_id = {}
        self._children_by_id = {}
        self._projected_row_by_id = {}
        self._path_nodes = {}
        self._page_number = 0
        self.endResetModel()
        self.pageChanged.emit(0, 0, 0)

    def set_entries(self, entries, filter_index=0):
        self.beginResetModel()
        self._all_entries = list(entries or [])
        self._filter_index = int(filter_index)
        self._rebuild_indexes()
        self._rebuild_projection()
        self._page_number = 0
        self._rebuild_page_children()
        self.endResetModel()
        self._emit_page_changed()

    def set_filter(self, filter_index: int):
        filter_index = int(filter_index)
        self._filter_index = filter_index
        self.set_entries(self._all_entries, filter_index)

    def _rebuild_indexes(self):
        self._entry_by_id = {}
        self._children_by_id = {}
        self._path_nodes = {}
        for entry in self._all_entries:
            sample_id = str(entry.get("data_id") or entry.get("id") or "")
            if not sample_id:
                continue
            entry["_node_kind"] = "sample"
            entry["_sample_id"] = sample_id
            self._entry_by_id[sample_id] = entry
            parent_path = str(entry.get("path") or "")
            if parent_path:
                self._path_nodes.setdefault(parent_path, (sample_id, None))
            valid_child_row = 0
            for media_source in entry.get("media_sources") or []:
                if not isinstance(media_source, dict):
                    continue
                child_path = str(media_source.get("path") or "")
                if child_path:
                    self._path_nodes.setdefault(child_path, (sample_id, valid_child_row))
                valid_child_row += 1

    def _entry_matches_filter(self, entry) -> bool:
        hand = bool(entry.get("hand_labelled"))
        smart = bool(entry.get("smart_labelled"))
        if self._filter_index == 1:
            return hand
        if self._filter_index == 2:
            return smart
        if self._filter_index == 3:
            return not (hand or smart)
        return True

    def _rebuild_projection(self):
        self._projected_entries = [entry for entry in self._all_entries if self._entry_matches_filter(entry)]
        self._projected_row_by_id = {
            str(entry.get("_sample_id") or ""): row
            for row, entry in enumerate(self._projected_entries)
        }

    def _page_bounds(self):
        start = self._page_number * self._page_size
        return start, min(start + self._page_size, len(self._projected_entries))

    def _rebuild_page_children(self):
        self._children_by_id = {}
        start, end = self._page_bounds()
        for entry in self._projected_entries[start:end]:
            sample_id = str(entry.get("_sample_id") or "")
            child_nodes = []
            for media_source in entry.get("media_sources") or []:
                if not isinstance(media_source, dict):
                    continue
                child_node = dict(media_source)
                child_node["_node_kind"] = "input"
                child_node["_sample_id"] = sample_id
                child_node["_child_row"] = len(child_nodes)
                child_nodes.append(child_node)
            self._children_by_id[sample_id] = child_nodes

    def _emit_page_changed(self):
        self.pageChanged.emit(*self.visible_range())

    def page_count(self):
        total = len(self._projected_entries)
        return (total + self._page_size - 1) // self._page_size

    def page_size(self):
        return self._page_size

    def page_number(self):
        return self._page_number

    def visible_range(self):
        total = len(self._projected_entries)
        if total == 0:
            return 0, 0, 0
        start, end = self._page_bounds()
        return start + 1, end, total

    def set_page(self, page_number: int):
        page_count = self.page_count()
        target = min(max(0, int(page_number)), max(0, page_count - 1))
        if target == self._page_number:
            return False
        self.beginResetModel()
        self._page_number = target
        self._rebuild_page_children()
        self.endResetModel()
        self._emit_page_changed()
        return True

    def set_page_size(self, page_size: int):
        target_size = normalize_explorer_page_size(page_size)
        if target_size == self._page_size:
            return False
        old_start, _old_end = self._page_bounds()
        self.beginResetModel()
        self._page_size = target_size
        self._page_number = old_start // self._page_size
        self._rebuild_page_children()
        self.endResetModel()
        self._emit_page_changed()
        return True

    def next_page(self):
        return self.set_page(self._page_number + 1)

    def previous_page(self):
        return self.set_page(self._page_number - 1)

    def page_for_sample_id(self, sample_id: str):
        row = self._projected_row_by_id.get(str(sample_id or ""))
        return None if row is None else row // self._page_size

    def ensure_sample_visible(self, sample_id: str):
        page_number = self.page_for_sample_id(sample_id)
        if page_number is None:
            return False
        self.set_page(page_number)
        return True

    def projected_row_for_sample_id(self, sample_id: str):
        return self._projected_row_by_id.get(str(sample_id or ""))

    def index_for_projected_row(self, projected_row: int, expose=False):
        projected_row = int(projected_row)
        if not 0 <= projected_row < len(self._projected_entries):
            return QModelIndex()
        if expose:
            self.set_page(projected_row // self._page_size)
        start, end = self._page_bounds()
        if not start <= projected_row < end:
            return QModelIndex()
        return self.index(projected_row - start, 0)

    def rowCount(self, parent=QModelIndex()):
        if not parent.isValid():
            start, end = self._page_bounds()
            return end - start
        node = parent.internalPointer()
        if isinstance(node, dict) and node.get("_node_kind") == "sample":
            return len(self._children_by_id.get(str(node.get("_sample_id") or ""), []))
        return 0

    def columnCount(self, _parent=QModelIndex()):
        return 1

    def index(self, row, column, parent=QModelIndex()):
        if row < 0 or column != 0:
            return QModelIndex()
        if not parent.isValid():
            start, end = self._page_bounds()
            if row >= end - start:
                return QModelIndex()
            return self.createIndex(row, column, self._projected_entries[start + row])
        parent_node = parent.internalPointer()
        if not isinstance(parent_node, dict) or parent_node.get("_node_kind") != "sample":
            return QModelIndex()
        children = self._children_by_id.get(str(parent_node.get("_sample_id") or ""), [])
        if row >= len(children):
            return QModelIndex()
        return self.createIndex(row, column, children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if not isinstance(node, dict) or node.get("_node_kind") != "input":
            return QModelIndex()
        sample_id = str(node.get("_sample_id") or "")
        row = self._projected_row_by_id.get(sample_id)
        start, end = self._page_bounds()
        if row is None or not start <= row < end:
            return QModelIndex()
        entry = self._entry_by_id.get(sample_id)
        return self.createIndex(row - start, 0, entry) if entry is not None else QModelIndex()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if not isinstance(node, dict):
            return None
        is_sample = node.get("_node_kind") == "sample"
        sample_id = str(node.get("_sample_id") or "")
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
            if is_sample:
                return str(node.get("display_name") or node.get("name") or sample_id)
            path = str(node.get("path") or "")
            ball_path = str(node.get("ball_path") or "")
            child_name = os.path.basename(path) or path
            if ball_path:
                child_name = f"{child_name}  (ball: {os.path.basename(ball_path) or ball_path})"
            return child_name
        if role == Qt.ItemDataRole.DecorationRole and is_sample:
            return node.get("status_icon")
        if role == Qt.ItemDataRole.ToolTipRole and not is_sample:
            path = str(node.get("path") or "")
            ball_path = str(node.get("ball_path") or "")
            return f"{path}\nBall H5: {ball_path}" if ball_path else path
        if role == self.FilePathRole:
            return node.get("path")
        if role == self.DataIdRole:
            return sample_id
        if role == self.SortRole:
            return node.get("sort_text") or _natural_sort_text(self.data(index, Qt.ItemDataRole.DisplayRole))
        if role == self.InputTypeRole and not is_sample:
            return str(node.get("type") or "")
        if role == self.BallPathRole and not is_sample:
            return str(node.get("ball_path") or "")
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        node = index.internalPointer()
        if isinstance(node, dict) and node.get("_node_kind") == "sample":
            flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.EditRole or not index.isValid() or index.parent().isValid():
            return False
        old_sample_id = str(index.data(self.DataIdRole) or "")
        requested_id = str(value or "").strip()
        marker = " (conf:"
        if requested_id.endswith(")") and marker in requested_id:
            requested_id = requested_id.rsplit(marker, 1)[0].strip()
        if not requested_id or requested_id == old_sample_id:
            return False
        QTimer.singleShot(0, lambda: self.renameRequested.emit(old_sample_id, requested_id))
        return True

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        if column != 0:
            return
        reverse = order == Qt.SortOrder.DescendingOrder
        entries = sorted(self._all_entries, key=lambda item: item.get("sort_text") or "", reverse=reverse)
        self.set_entries(entries, self._filter_index)

    def index_for_sample_id(self, sample_id: str, expose=False):
        row = self._projected_row_by_id.get(str(sample_id or ""))
        if row is None:
            return QModelIndex()
        if expose:
            self.ensure_sample_visible(sample_id)
        return self.index_for_projected_row(row)

    def index_for_path(self, path: str, expose=False):
        node_ref = self._path_nodes.get(str(path or ""))
        if node_ref is None:
            return QModelIndex()
        sample_id, child_row = node_ref
        parent_index = self.index_for_sample_id(sample_id, expose=expose)
        if not parent_index.isValid() or child_row is None:
            return parent_index
        return self.index(child_row, 0, parent_index)

    def refresh_sample(self, sample_id: str):
        index = self.index_for_sample_id(sample_id)
        if index.isValid():
            self.dataChanged.emit(index, index)

    @staticmethod
    def entry_display_name(name: str, confidence_score: float = None) -> str:
        display_name = str(name or "")
        if confidence_score is not None:
            display_name = f"{display_name} (conf:{float(confidence_score):.2f})"
        return display_name


class DatasetExplorerPanel(QWidget):
    """
    Dataset Explorer view backed by a Qt Designer .ui file.
    """

    removeItemRequested = pyqtSignal(QModelIndex)
    associateBallH5Requested = pyqtSignal(QModelIndex)
    clearBallH5Requested = pyqtSignal(QModelIndex)
    addDataRequested = pyqtSignal()
    addInputRequested = pyqtSignal(QModelIndex)
    sampleNavigateRequested = pyqtSignal(int)
    pageNavigateRequested = pyqtSignal(int)
    pageRequested = pyqtSignal(int)
    headerDraftChanged = pyqtSignal(dict)
    confidenceSortToggled = pyqtSignal(bool)

    _HEADER_VALUE_ROLE = Qt.ItemDataRole.UserRole + 200
    _HEADER_HAS_VALUE_ROLE = Qt.ItemDataRole.UserRole + 201
    _MISSING = object()

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
            os.path.join("ui", "dataset_explorer_panel", "dataset_explorer_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load DatasetExplorerPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        self.tree_model = DatasetExplorerTreeModel(self)
        self.tree.setModel(self.tree_model)
        self._header_key_order = [
            "version",
            "date",
            "dataset_name",
            "description",
            "metadata",
        ]
        self._header_known = {}
        self._header_unknown = {}
        self._header_draft = {}
        self._suspend_header_signals = False

        self._configure_widgets(tree_title, filter_items, clear_text)
        self.tree_model.pageChanged.connect(self._update_page_range)
        self.btn_add_data.clicked.connect(self.addDataRequested.emit)
        self.btn_prev_sample.clicked.connect(lambda: self.sampleNavigateRequested.emit(-1))
        self.btn_next_sample.clicked.connect(lambda: self.sampleNavigateRequested.emit(1))
        self.btn_prev_page.clicked.connect(lambda: self._request_adjacent_page(-1))
        self.btn_next_page.clicked.connect(lambda: self._request_adjacent_page(1))
        self.page_number_spin.valueChanged.connect(self._request_page_from_spin)
        self._set_context_menu_enabled(enable_context_menu)

    def _configure_widgets(self, tree_title, filter_items, clear_text):
        self.lbl_title.setText(tree_title)
        self.lbl_title.setProperty("class", "panel_header_lbl")

        self.clear_btn.setText(clear_text)
        self.clear_btn.setObjectName("panel_clear_btn")

        self.filter_combo.clear()
        if filter_items:
            self.filter_combo.addItems(filter_items)
        self.sort_conf_checkbox = QCheckBox("Sort by conf", self)
        self.sort_conf_checkbox.setObjectName("sort_conf_checkbox")
        self.bottomLayout.insertWidget(2, self.sort_conf_checkbox)
        self.sort_conf_checkbox.toggled.connect(self.confidenceSortToggled.emit)
        self.bottomLayout.setStretch(1, 1)

        self.tree.setHeaderHidden(True)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(True)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.viewport().installEventFilter(self)
        self.page_range_label = QLabel("No samples", self)
        self.page_range_label.setObjectName("dataset_page_range_label")
        self.page_range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verticalLayout_tab_data.insertWidget(2, self.page_range_label)
        self._configure_pagination_controls()
        self.json_raw_text.setReadOnly(True)
        self.json_raw_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._configure_header_tables()

    def _configure_pagination_controls(self):
        self.pagination_layout = QHBoxLayout()
        self.pagination_layout.setObjectName("datasetPaginationLayout")

        self.btn_prev_page = QToolButton(self)
        self.btn_prev_page.setObjectName("btn_prev_page")
        self.btn_prev_page.setText("‹")
        self.btn_prev_page.setToolTip("Previous Page")

        page_label = QLabel("Page", self)
        page_label.setObjectName("dataset_page_label")

        self.page_number_spin = QSpinBox(self)
        self.page_number_spin.setObjectName("page_number_spin")
        self.page_number_spin.setRange(0, 0)
        self.page_number_spin.setValue(0)
        self.page_number_spin.setKeyboardTracking(False)
        self.page_number_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_number_spin.setMaximumWidth(72)

        self.page_count_label = QLabel("of 0", self)
        self.page_count_label.setObjectName("dataset_page_count_label")

        self.btn_next_page = QToolButton(self)
        self.btn_next_page.setObjectName("btn_next_page")
        self.btn_next_page.setText("›")
        self.btn_next_page.setToolTip("Next Page")

        self.pagination_layout.addStretch(1)
        self.pagination_layout.addWidget(self.btn_prev_page)
        self.pagination_layout.addWidget(page_label)
        self.pagination_layout.addWidget(self.page_number_spin)
        self.pagination_layout.addWidget(self.page_count_label)
        self.pagination_layout.addWidget(self.btn_next_page)
        self.pagination_layout.addStretch(1)
        self.verticalLayout_tab_data.insertLayout(2, self.pagination_layout)
        self._sync_pagination_controls()

    def _sync_pagination_controls(self):
        page_count = self.tree_model.page_count()
        current_page = self.tree_model.page_number() + 1 if page_count else 0
        blocker = QSignalBlocker(self.page_number_spin)
        if page_count:
            self.page_number_spin.setRange(1, page_count)
            self.page_number_spin.setValue(current_page)
        else:
            self.page_number_spin.setRange(0, 0)
            self.page_number_spin.setValue(0)
        del blocker
        self.page_count_label.setText(f"of {page_count:,}")
        self.page_number_spin.setEnabled(page_count > 1)
        self.btn_prev_page.setEnabled(current_page > 1)
        self.btn_next_page.setEnabled(0 < current_page < page_count)

    def _request_page_from_spin(self, page_number: int):
        if self.tree_model.page_count() > 0:
            self.pageRequested.emit(int(page_number) - 1)

    def _request_adjacent_page(self, step: int):
        self.pageRequested.emit(self.tree_model.page_number() + (1 if step > 0 else -1))

    def _update_page_range(self, first: int, last: int, total: int):
        self._sync_pagination_controls()
        if total <= 0:
            self.page_range_label.setText("No samples")
            return
        self.page_range_label.setText(f"Showing {first:,}–{last:,} of {total:,}")

    def eventFilter(self, watched, event):
        if watched is self.tree.viewport() and event.type() == QEvent.Type.Wheel:
            delta = event.angleDelta().y() or event.pixelDelta().y()
            scroll_bar = self.tree.verticalScrollBar()
            if (
                delta < 0
                and scroll_bar.value() >= scroll_bar.maximum()
                and self.tree_model.page_number() + 1 < self.tree_model.page_count()
            ):
                self.pageNavigateRequested.emit(1)
                return True
            if (
                delta > 0
                and scroll_bar.value() <= scroll_bar.minimum()
                and self.tree_model.page_number() > 0
            ):
                self.pageNavigateRequested.emit(-1)
                return True
        return super().eventFilter(watched, event)

    def _configure_header_tables(self):
        self._configure_single_header_table(self.table_header_known, editable=True)
        self._configure_single_header_table(self.table_header_unknown, editable=False)
        self.table_header_known.itemChanged.connect(self._on_known_header_item_changed)
        self.table_header_known.cellDoubleClicked.connect(self._on_known_header_cell_double_clicked)

    def _configure_single_header_table(self, table, editable: bool):
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Key", "Value"])
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setWordWrap(True)
        table.setTextElideMode(Qt.TextElideMode.ElideNone)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        if editable:
            table.setEditTriggers(
                QAbstractItemView.EditTrigger.DoubleClicked
                | QAbstractItemView.EditTrigger.EditKeyPressed
                | QAbstractItemView.EditTrigger.SelectedClicked
            )
        else:
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

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
        ball_target_index = self._ball_h5_target_index(index)
        if ball_target_index.isValid():
            associate_action = menu.addAction("Associate Ball H5...")
            current_ball_path = ball_target_index.data(self.tree_model.BallPathRole) or ""
            clear_ball_action = menu.addAction("Remove Ball H5 Association")
            clear_ball_action.setEnabled(bool(current_ball_path))
            menu.addSeparator()
        else:
            associate_action = None
            clear_ball_action = None

        if not index.parent().isValid():
            add_input_action = menu.addAction("Add Input...")
            menu.addSeparator()
        else:
            add_input_action = None

        remove_label = "Remove Input" if index.parent().isValid() else "Remove Sample"
        remove_action = menu.addAction(remove_label)
        selected = menu.exec(self.tree.mapToGlobal(pos))
        if associate_action is not None and selected == associate_action:
            self.associateBallH5Requested.emit(ball_target_index)
        elif clear_ball_action is not None and selected == clear_ball_action:
            self.clearBallH5Requested.emit(ball_target_index)
        elif add_input_action is not None and selected == add_input_action:
            self.addInputRequested.emit(index)
        elif selected == remove_action:
            self.removeItemRequested.emit(index)

    def _ball_h5_target_index(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        if index.parent().isValid():
            input_type = index.data(self.tree_model.InputTypeRole)
            if input_type in {"player_joints_h5", "player_centroids_h5"}:
                return index
            return QModelIndex()

        joint_child_indexes = []
        for row in range(self.tree_model.rowCount(index)):
            child = self.tree_model.index(row, 0, index)
            if child.isValid() and child.data(self.tree_model.InputTypeRole) in {"player_joints_h5", "player_centroids_h5"}:
                joint_child_indexes.append(child)
        if len(joint_child_indexes) == 1:
            return joint_child_indexes[0]
        return QModelIndex()

    # ------------------------------------------------------------------
    # Header Inspector API
    # ------------------------------------------------------------------
    def set_header_rows(self, known: dict, unknown: dict, draft: dict = None, key_order=None):
        self._suspend_header_signals = True
        self._header_known = copy.deepcopy(known or {})
        self._header_unknown = copy.deepcopy(unknown or {})
        self._header_draft = copy.deepcopy(draft or {})
        if key_order:
            self._header_key_order = list(key_order)

        self._populate_known_table()
        self._populate_unknown_table()
        self._suspend_header_signals = False

    def clear_header_rows(self):
        self.set_header_rows({}, {}, {})

    def set_raw_json_text(self, raw_json: str):
        self.json_raw_text.setPlainText(raw_json or "")

    def clear_raw_json_text(self):
        self.json_raw_text.clear()

    def get_staged_header_draft(self):
        return copy.deepcopy(self._header_draft)

    def _populate_known_table(self):
        table = self.table_header_known
        table.setRowCount(0)
        default_row_height = table.verticalHeader().defaultSectionSize()
        line_height = max(1, table.fontMetrics().lineSpacing())
        for row, key in enumerate(self._header_key_order):
            table.insertRow(row)

            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, key_item)

            value = self._value_for_known_key(key)
            has_value = value is not self._MISSING
            display = self._stringify_header_value(value if has_value else "")

            value_item = QTableWidgetItem(display)
            value_item.setData(self._HEADER_HAS_VALUE_ROLE, has_value)
            value_item.setData(
                self._HEADER_VALUE_ROLE,
                copy.deepcopy(value) if has_value else None,
            )

            is_nested = key == "metadata" or (
                has_value and isinstance(value, (dict, list))
            )
            if is_nested:
                value_item.setToolTip("Double-click to edit JSON object/array.")
                value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, value_item)

            if key == "description":
                # Keep long descriptions readable in-place (about 5 text lines).
                table.setRowHeight(row, line_height * 5 + 8)
            else:
                table.setRowHeight(row, default_row_height)

    def _populate_unknown_table(self):
        table = self.table_header_unknown
        table.setRowCount(0)
        for row, (key, value) in enumerate(self._header_unknown.items()):
            table.insertRow(row)
            key_item = QTableWidgetItem(str(key))
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 0, key_item)

            value_item = QTableWidgetItem(self._stringify_header_value(value))
            value_item.setFlags(value_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, 1, value_item)

    def _value_for_known_key(self, key: str):
        if key in self._header_draft:
            return self._header_draft[key]
        if key in self._header_known:
            return self._header_known[key]
        return self._MISSING

    def _stringify_header_value(self, value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        return str(value)

    def _on_known_header_item_changed(self, item: QTableWidgetItem):
        if self._suspend_header_signals:
            return
        if item.column() != 1:
            return

        row = item.row()
        key_item = self.table_header_known.item(row, 0)
        if not key_item:
            return
        key = key_item.text()

        has_existing_value = bool(item.data(self._HEADER_HAS_VALUE_ROLE))
        existing_value = item.data(self._HEADER_VALUE_ROLE)
        new_text = item.text()
        if has_existing_value:
            parsed = self._parse_scalar_value(new_text, existing_value)
        else:
            if new_text == "":
                self._set_draft_value(key, self._MISSING)
                return
            parsed = new_text
        self._set_draft_value(key, parsed)

    def _on_known_header_cell_double_clicked(self, row: int, column: int):
        if column != 1:
            return
        key_item = self.table_header_known.item(row, 0)
        if not key_item:
            return
        key = key_item.text()

        current = self._value_for_known_key(key)
        if current is self._MISSING:
            # Allow easy initialization for nested known fields.
            if key == "metadata":
                current = {}
            else:
                return

        if not isinstance(current, (dict, list)):
            return

        updated = self._open_json_value_dialog(key, current)
        if updated is self._MISSING:
            return
        self._set_draft_value(key, updated)

    def _open_json_value_dialog(self, key: str, current_value):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Edit JSON: {key}")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)

        editor = QPlainTextEdit(dialog)
        editor.setPlainText(json.dumps(current_value, indent=2, ensure_ascii=False))
        layout.addWidget(editor)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        layout.addWidget(buttons)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        while True:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return self._MISSING
            raw = editor.toPlainText().strip()
            try:
                value = json.loads(raw) if raw else None
            except Exception as exc:
                QMessageBox.warning(self, "Invalid JSON", f"Could not parse JSON:\n{exc}")
                continue
            if not isinstance(value, (dict, list)):
                QMessageBox.warning(self, "Invalid Type", "Value must be a JSON object or array.")
                continue
            return value

    def _parse_scalar_value(self, text: str, template):
        if isinstance(template, bool):
            lowered = text.strip().lower()
            if lowered in ("true", "1", "yes"):
                return True
            if lowered in ("false", "0", "no"):
                return False
            return template
        if isinstance(template, int) and not isinstance(template, bool):
            try:
                return int(text)
            except Exception:
                return template
        if isinstance(template, float):
            try:
                return float(text)
            except Exception:
                return template
        if template is None:
            return None if text.strip().lower() == "null" else text
        return text

    def _set_draft_value(self, key: str, value):
        baseline = self._header_known.get(key, self._MISSING)
        if value is self._MISSING:
            self._header_draft.pop(key, None)
        elif baseline is not self._MISSING and baseline == value:
            self._header_draft.pop(key, None)
        else:
            self._header_draft[key] = copy.deepcopy(value)

        self._suspend_header_signals = True
        self._populate_known_table()
        self._suspend_header_signals = False
        self.headerDraftChanged.emit(copy.deepcopy(self._header_draft))
