import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QLabel, QMenu, QTabWidget, QVBoxLayout, QWidget

from utils import resource_path


class QuestionAnswerAnnotationPanel(QWidget):
    """
    Question/Answer annotation panel.
    - Shared question tabs are dataset-level.
    - Question tabs show read-only question text.
    - A trailing '+' tab triggers question creation.
    - Tab context menu provides rename/delete actions.
    - Answer editor is sample-level and controlled by selection state.
    """

    questionAddRequested = pyqtSignal()
    questionRenameRequested = pyqtSignal(str)
    questionDeleteRequested = pyqtSignal(str)
    questionSelectionChanged = pyqtSignal(str)
    answerTextChanged = pyqtSignal()

    _PLUS_TAB_LABEL = "+"

    def __init__(self, parent=None):
        super().__init__(parent)

        ui_path = resource_path(
            os.path.join("ui", "question_answer", "question_answer_annotation_panel.ui")
        )
        try:
            uic.loadUi(ui_path, self)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to load QuestionAnswerAnnotationPanel UI: {ui_path}. Reason: {exc}"
            ) from exc

        # Stable controller-facing aliases.
        self.question_tabs: QTabWidget = self.questionTabs
        self.answer_editor = self.answerEditor

        # Remove placeholder tab from .ui and build tabs dynamically from dataset context.
        self.question_tabs.clear()

        self._suspend_tab_change = False
        self._last_selected_question_tab_index = -1

        tab_bar = self.question_tabs.tabBar()
        tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_bar.customContextMenuRequested.connect(self._on_tab_context_menu_requested)
        tab_bar.tabBarClicked.connect(self._on_tab_bar_clicked)

        self.question_tabs.currentChanged.connect(self._on_current_tab_changed)
        self.answer_editor.textChanged.connect(self.answerTextChanged.emit)

    def set_questions(self, questions, selected_question_id: str = ""):
        selected_question_id = str(selected_question_id or "")

        valid_questions = []
        for entry in list(questions or []):
            if not isinstance(entry, dict):
                continue
            question_id = str(entry.get("id") or "").strip()
            question_text = str(entry.get("question") or "").strip()
            if not question_id or not question_text:
                continue
            valid_questions.append({"id": question_id, "question": question_text})

        self._suspend_tab_change = True
        try:
            self.question_tabs.blockSignals(True)
            self.question_tabs.clear()

            selected_index = -1
            for entry in valid_questions:
                tab_widget = self._build_question_tab(entry["question"])
                tab_index = self.question_tabs.addTab(tab_widget, entry["id"])
                self.question_tabs.tabBar().setTabData(tab_index, entry["id"])
                self.question_tabs.setTabToolTip(tab_index, entry["question"])
                if entry["id"] == selected_question_id:
                    selected_index = tab_index

            plus_index = self.question_tabs.addTab(QWidget(), self._PLUS_TAB_LABEL)
            self.question_tabs.tabBar().setTabData(plus_index, None)
            self.question_tabs.setTabToolTip(plus_index, "Add a new question")

            if selected_index < 0 and valid_questions:
                selected_index = 0

            if selected_index >= 0:
                self.question_tabs.setCurrentIndex(selected_index)
                self._last_selected_question_tab_index = selected_index
            else:
                self.question_tabs.setCurrentIndex(plus_index)
                self._last_selected_question_tab_index = -1
        finally:
            self.question_tabs.blockSignals(False)
            self._suspend_tab_change = False

        self.questionSelectionChanged.emit(self.get_selected_question_id())

    def get_selected_question_id(self) -> str:
        tab_index = int(self.question_tabs.currentIndex())
        if tab_index < 0:
            return ""
        question_id = self.question_tabs.tabBar().tabData(tab_index)
        return str(question_id or "")

    def set_question_bank_enabled(self, enabled: bool):
        self.question_tabs.setEnabled(bool(enabled))

    def set_answer_editor_enabled(self, enabled: bool):
        self.answer_editor.setEnabled(bool(enabled))

    def set_answer_text(self, text: str):
        self.answer_editor.setPlainText(str(text or ""))

    def get_answer_text(self) -> str:
        return self.answer_editor.toPlainText()

    def _build_question_tab(self, question_text: str) -> QWidget:
        tab_widget = QWidget()
        layout = QVBoxLayout(tab_widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)

        question_label = QLabel(str(question_text or ""))
        question_label.setWordWrap(True)
        question_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(question_label)
        return tab_widget

    def _on_current_tab_changed(self, tab_index: int):
        if self._suspend_tab_change:
            return

        if tab_index < 0:
            self.questionSelectionChanged.emit("")
            return

        question_id = self._question_id_for_tab_index(tab_index)
        if question_id:
            self._last_selected_question_tab_index = tab_index
            self.questionSelectionChanged.emit(question_id)
            return

        # '+' tab selected: restore previous question tab first, then trigger add flow.
        restore_index = self._last_selected_question_tab_index
        if restore_index < 0 or restore_index >= self._question_tab_count():
            self.questionSelectionChanged.emit("")
            self.questionAddRequested.emit()
            return

        self._suspend_tab_change = True
        try:
            self.question_tabs.setCurrentIndex(restore_index)
        finally:
            self._suspend_tab_change = False
        restored_question_id = self._question_id_for_tab_index(restore_index)
        self.questionSelectionChanged.emit(restored_question_id)
        self.questionAddRequested.emit()

    def _on_tab_context_menu_requested(self, pos):
        if not self.question_tabs.isEnabled():
            return

        tab_bar = self.question_tabs.tabBar()
        tab_index = tab_bar.tabAt(pos)
        if tab_index < 0:
            return

        question_id = self._question_id_for_tab_index(tab_index)
        if not question_id:
            return

        if self.question_tabs.currentIndex() != tab_index:
            self.question_tabs.setCurrentIndex(tab_index)

        menu = QMenu(self)
        rename_action = menu.addAction("Rename Question")
        delete_action = menu.addAction("Delete Question")
        selected_action = menu.exec(tab_bar.mapToGlobal(pos))
        if selected_action == rename_action:
            self.questionRenameRequested.emit(question_id)
        elif selected_action == delete_action:
            self.questionDeleteRequested.emit(question_id)

    def _on_tab_bar_clicked(self, tab_index: int):
        if tab_index < 0:
            return
        if self._question_id_for_tab_index(tab_index):
            return
        # Handle '+' when it is already selected; currentChanged is not emitted in that case.
        if tab_index != self.question_tabs.currentIndex():
            return

        restore_index = self._last_selected_question_tab_index
        if restore_index < 0 or restore_index >= self._question_tab_count():
            self.questionSelectionChanged.emit("")
            self.questionAddRequested.emit()
            return

        self._suspend_tab_change = True
        try:
            self.question_tabs.setCurrentIndex(restore_index)
        finally:
            self._suspend_tab_change = False
        self.questionSelectionChanged.emit(self._question_id_for_tab_index(restore_index))
        self.questionAddRequested.emit()

    def _question_tab_count(self) -> int:
        count = int(self.question_tabs.count())
        return max(0, count - 1)

    def _question_id_for_tab_index(self, tab_index: int) -> str:
        if tab_index < 0 or tab_index >= self.question_tabs.count():
            return ""
        tab_data = self.question_tabs.tabBar().tabData(tab_index)
        return str(tab_data or "")


__all__ = ["QuestionAnswerAnnotationPanel"]
