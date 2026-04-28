import os

from PyQt6 import uic
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QPushButton, QWidget

from utils import resource_path


class QuestionAnswerAnnotationPanel(QWidget):
    """
    Presents sample-local grouped VQA annotations.
    """

    questionGroupAddRequested = pyqtSignal()
    questionGroupEditRequested = pyqtSignal(int)
    questionGroupDeleteRequested = pyqtSignal(int)
    questionGroupSelectionChanged = pyqtSignal(int)
    answerAddRequested = pyqtSignal()
    answerEditRequested = pyqtSignal(int)
    answerDeleteRequested = pyqtSignal(int)
    answerSelectionChanged = pyqtSignal(int)

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

        self.question_list: QListWidget = self.questionList
        self.add_question_button: QPushButton = self.addQuestionButton
        self.answer_list: QListWidget = self.answerList
        self.add_answer_button: QPushButton = self.addAnswerButton

        self._suspend_changes = False

        self.add_question_button.clicked.connect(self.questionGroupAddRequested.emit)
        self.question_list.currentRowChanged.connect(self.questionGroupSelectionChanged.emit)
        self.question_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.question_list.customContextMenuRequested.connect(
            self._on_question_context_menu_requested
        )
        self.question_list.itemDoubleClicked.connect(self._on_question_item_double_clicked)

        self.add_answer_button.clicked.connect(self.answerAddRequested.emit)
        self.answer_list.currentRowChanged.connect(self.answerSelectionChanged.emit)
        self.answer_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.answer_list.customContextMenuRequested.connect(self._on_answer_context_menu_requested)
        self.answer_list.itemDoubleClicked.connect(self._on_answer_item_double_clicked)

    def set_question_groups(self, groups, selected_group_index: int = 0, selected_answer_index: int = 0):
        valid_groups = []
        for group in list(groups or []):
            if not isinstance(group, dict):
                continue
            question = str(group.get("question") or "")
            answers = [str(answer or "") for answer in list(group.get("answers") or [])]
            valid_groups.append({"question": question, "answers": answers})

        self._suspend_changes = True
        try:
            self._block_editor_signals(True)
            self.question_list.clear()
            for index, group in enumerate(valid_groups, start=1):
                item = QListWidgetItem(self._question_label(group, index))
                item.setData(Qt.ItemDataRole.UserRole, index - 1)
                self.question_list.addItem(item)

            if valid_groups:
                selected_group_index = self._bounded_index(selected_group_index, len(valid_groups))
                self.question_list.setCurrentRow(selected_group_index)
                self.set_answer_rows(
                    valid_groups[selected_group_index].get("answers", []),
                    selected_answer_index=selected_answer_index,
                )
            else:
                self.question_list.setCurrentRow(-1)
                self.set_answer_rows([], selected_answer_index=-1)
        finally:
            self._block_editor_signals(False)
            self._suspend_changes = False

    def set_answer_rows(self, answers, selected_answer_index: int = 0):
        answer_texts = [str(answer or "") for answer in list(answers or [])]

        self._suspend_changes = True
        try:
            self._block_answer_signals(True)
            self.answer_list.clear()
            for index, answer_text in enumerate(answer_texts, start=1):
                item = QListWidgetItem(self._answer_label(answer_text, index))
                item.setData(Qt.ItemDataRole.UserRole, index - 1)
                self.answer_list.addItem(item)

            if answer_texts:
                selected_answer_index = self._bounded_index(selected_answer_index, len(answer_texts))
                self.answer_list.setCurrentRow(selected_answer_index)
            else:
                self.answer_list.setCurrentRow(-1)
        finally:
            self._block_answer_signals(False)
            self._suspend_changes = False

    def get_selected_group_index(self) -> int:
        return int(self.question_list.currentRow())

    def get_selected_answer_index(self) -> int:
        return int(self.answer_list.currentRow())

    def set_controls_enabled(
        self,
        *,
        editor_enabled: bool,
        has_group: bool,
        has_answer: bool,
    ):
        editor_enabled = bool(editor_enabled)
        has_group = bool(has_group)
        has_answer = bool(has_answer)

        self.question_list.setEnabled(editor_enabled)
        self.add_question_button.setEnabled(editor_enabled)

        self.answer_list.setEnabled(editor_enabled and has_group)
        self.add_answer_button.setEnabled(editor_enabled and has_group)

    def refresh_question_label(self, group: dict, index: int):
        item = self.question_list.item(index)
        if item is not None:
            item.setText(self._question_label(group, index + 1))

    def refresh_answer_label(self, answer_text: str, index: int):
        item = self.answer_list.item(index)
        if item is not None:
            item.setText(self._answer_label(answer_text, index + 1))

    def _block_editor_signals(self, blocked: bool):
        self.question_list.blockSignals(blocked)
        self._block_answer_signals(blocked)

    def _on_question_context_menu_requested(self, pos):
        item = self.question_list.itemAt(pos)
        if item is None:
            return
        row = self.question_list.row(item)
        if row < 0:
            return
        self.question_list.setCurrentRow(row)

        menu = QMenu(self)
        edit_action = menu.addAction("Edit Question")
        remove_action = menu.addAction("Remove Question")
        selected_action = menu.exec(self.question_list.viewport().mapToGlobal(pos))
        if selected_action == edit_action:
            self.questionGroupEditRequested.emit(row)
        elif selected_action == remove_action:
            self.questionGroupDeleteRequested.emit(row)

    def _on_question_item_double_clicked(self, item):
        if item is None:
            return
        row = self.question_list.row(item)
        if row >= 0:
            self.questionGroupEditRequested.emit(row)

    def _on_answer_context_menu_requested(self, pos):
        item = self.answer_list.itemAt(pos)
        if item is None:
            return
        row = self.answer_list.row(item)
        if row < 0:
            return
        self.answer_list.setCurrentRow(row)

        menu = QMenu(self)
        edit_action = menu.addAction("Edit Answer")
        remove_action = menu.addAction("Remove Answer")
        selected_action = menu.exec(self.answer_list.viewport().mapToGlobal(pos))
        if selected_action == edit_action:
            self.answerEditRequested.emit(row)
        elif selected_action == remove_action:
            self.answerDeleteRequested.emit(row)

    def _on_answer_item_double_clicked(self, item):
        if item is None:
            return
        row = self.answer_list.row(item)
        if row >= 0:
            self.answerEditRequested.emit(row)

    def _block_answer_signals(self, blocked: bool):
        self.answer_list.blockSignals(blocked)

    @staticmethod
    def _bounded_index(index: int, size: int) -> int:
        if size <= 0:
            return -1
        try:
            index = int(index)
        except Exception:
            index = 0
        return min(max(index, 0), size - 1)

    @staticmethod
    def _question_label(group: dict, index: int) -> str:
        question = str(group.get("question") or "").strip()
        if not question:
            question = f"Question {index}"
        return question if len(question) <= 80 else f"{question[:77]}..."

    @staticmethod
    def _answer_label(answer_text: str, index: int) -> str:
        answer = str(answer_text or "").strip()
        if not answer:
            return f"Answer {index}"
        return answer if len(answer) <= 80 else f"{answer[:77]}..."


__all__ = ["QuestionAnswerAnnotationPanel"]
