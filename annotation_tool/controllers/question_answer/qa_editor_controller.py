import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtWidgets import QInputDialog


class QAEditorController(QObject):
    """
    Question/Answer editor controller.
    Owns shared question bank actions and per-sample answer editing.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    qaQuestionAddRequested = pyqtSignal(str)
    qaQuestionRenameRequested = pyqtSignal(str, str)
    qaQuestionDeleteRequested = pyqtSignal(str)
    qaAnswersUpdateRequested = pyqtSignal(str, object)

    def __init__(self, question_answer_panel):
        super().__init__()
        self.question_answer_panel = question_answer_panel

        self._active_mode_index = 0
        self._selection_enabled = False
        self._question_bank_enabled = False
        self._suspend_autosave = False
        self._pending_select_question_id = ""

        self._question_bank = []
        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answers_by_question_id = {}

        self._autosave_timer = QTimer(self.question_answer_panel)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self.save_current_answers)

    def setup_connections(self):
        self.question_answer_panel.questionAddRequested.connect(self._on_add_question_requested)
        self.question_answer_panel.questionRenameRequested.connect(self._on_rename_question_requested)
        self.question_answer_panel.questionDeleteRequested.connect(self._on_delete_question_requested)
        self.question_answer_panel.questionSelectionChanged.connect(self._on_question_selection_changed)
        self.question_answer_panel.answerTextChanged.connect(self._on_answer_text_changed)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index

    def set_question_bank_enabled(self, enabled: bool):
        self._question_bank_enabled = bool(enabled)
        self.question_answer_panel.set_question_bank_enabled(self._question_bank_enabled)
        self._update_answer_editor_enabled()

    def set_sample_selection_enabled(self, enabled: bool):
        self._selection_enabled = bool(enabled)
        self._update_answer_editor_enabled()

    def reset_ui(self):
        self._autosave_timer.stop()
        self._selection_enabled = False
        self._question_bank_enabled = False
        self._pending_select_question_id = ""
        self._question_bank = []
        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answers_by_question_id = {}

        self.question_answer_panel.set_questions([])
        self._set_answer_text("")
        self.question_answer_panel.set_question_bank_enabled(False)
        self.question_answer_panel.set_answer_editor_enabled(False)

    def on_question_bank_changed(self, questions):
        self._question_bank = self._normalize_questions(questions)
        valid_ids = {question["id"] for question in self._question_bank}
        self._answers_by_question_id = {
            question_id: answer
            for question_id, answer in self._answers_by_question_id.items()
            if question_id in valid_ids
        }

        selected_question_id = self.question_answer_panel.get_selected_question_id()
        if self._pending_select_question_id and self._pending_select_question_id in valid_ids:
            selected_question_id = self._pending_select_question_id
        elif selected_question_id not in valid_ids:
            selected_question_id = self._question_bank[0]["id"] if self._question_bank else ""

        self._pending_select_question_id = ""
        self.question_answer_panel.set_questions(self._question_bank, selected_question_id=selected_question_id)
        self.question_answer_panel.set_question_bank_enabled(self._question_bank_enabled)

        if selected_question_id:
            self._set_answer_text(self._answers_by_question_id.get(selected_question_id, ""))
        else:
            self._set_answer_text("")
        self._update_answer_editor_enabled()

    def on_selected_sample_changed(self, sample):
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self.save_current_answers()

        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answers_by_question_id = {}

        if isinstance(sample, dict):
            sample_id = str(sample.get("id") or "")
            if sample_id:
                self.current_sample_id = sample_id
                self._current_sample_snapshot = copy.deepcopy(sample)
                self._answers_by_question_id = self._answers_map_from_sample(sample)

        selected_question_id = self.question_answer_panel.get_selected_question_id()
        if selected_question_id:
            self._set_answer_text(self._answers_by_question_id.get(selected_question_id, ""))
        else:
            self._set_answer_text("")
        self._update_answer_editor_enabled()

    def _on_add_question_requested(self):
        text, accepted = QInputDialog.getText(
            self.question_answer_panel,
            "Add Question",
            "Question:",
        )
        if not accepted:
            return

        question_text = str(text or "").strip()
        if not question_text:
            return

        if any(entry["question"].lower() == question_text.lower() for entry in self._question_bank):
            self.statusMessageRequested.emit("Duplicate", "Question already exists.", 1500)
            return

        self._pending_select_question_id = self._next_question_id_from_bank()
        self.qaQuestionAddRequested.emit(question_text)

    def _on_rename_question_requested(self, question_id: str):
        target_id = str(question_id or "").strip()
        if not target_id:
            return

        current_question = self._question_text_for_id(target_id)
        if not current_question:
            return

        text, accepted = QInputDialog.getText(
            self.question_answer_panel,
            "Rename Question",
            "Question:",
            text=current_question,
        )
        if not accepted:
            return

        new_text = str(text or "").strip()
        if not new_text or new_text == current_question:
            return

        if any(
            entry["id"] != target_id and entry["question"].lower() == new_text.lower()
            for entry in self._question_bank
        ):
            self.statusMessageRequested.emit("Duplicate", "Question already exists.", 1500)
            return

        self._pending_select_question_id = target_id
        self.qaQuestionRenameRequested.emit(target_id, new_text)

    def _on_delete_question_requested(self, question_id: str):
        target_id = str(question_id or "").strip()
        if not target_id:
            return

        current_question = self._question_text_for_id(target_id)
        if not current_question:
            return

        self.qaQuestionDeleteRequested.emit(target_id)
        self._answers_by_question_id.pop(target_id, None)

    def _on_question_selection_changed(self, question_id: str):
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self.save_current_answers()

        selected_id = str(question_id or "")
        if selected_id:
            self._set_answer_text(self._answers_by_question_id.get(selected_id, ""))
        else:
            self._set_answer_text("")
        self._update_answer_editor_enabled()

    def _on_answer_text_changed(self):
        if self._suspend_autosave:
            return
        if not self.current_sample_id:
            return

        question_id = self.question_answer_panel.get_selected_question_id()
        if not question_id:
            return

        self._answers_by_question_id[str(question_id)] = self.question_answer_panel.get_answer_text()
        self._autosave_timer.start()

    def save_current_answers(self):
        if not self.current_sample_id:
            return False

        new_answers = self._answers_list_from_map(self._answers_by_question_id)
        old_answers = self._normalized_answers_list(self._current_sample_snapshot.get("answers"))
        if old_answers == new_answers:
            return False

        self.qaAnswersUpdateRequested.emit(self.current_sample_id, copy.deepcopy(new_answers))
        if new_answers:
            self._current_sample_snapshot["answers"] = copy.deepcopy(new_answers)
        else:
            self._current_sample_snapshot.pop("answers", None)
        return True

    def _update_answer_editor_enabled(self):
        has_sample = bool(self.current_sample_id)
        has_question = bool(self.question_answer_panel.get_selected_question_id())
        enabled = bool(self._selection_enabled and has_sample and has_question)
        self.question_answer_panel.set_answer_editor_enabled(enabled)

    def _set_answer_text(self, text: str):
        self._suspend_autosave = True
        try:
            self.question_answer_panel.set_answer_text(text)
        finally:
            self._suspend_autosave = False

    def _question_text_for_id(self, question_id: str) -> str:
        for entry in self._question_bank:
            if entry["id"] == question_id:
                return entry["question"]
        return ""

    def _normalize_questions(self, questions) -> list:
        normalized = []
        seen_ids = set()
        for raw_entry in list(questions or []):
            if not isinstance(raw_entry, dict):
                continue
            question_id = str(raw_entry.get("id") or "").strip()
            question_text = str(raw_entry.get("question") or "").strip()
            if not question_id or not question_text:
                continue
            if question_id in seen_ids:
                continue
            seen_ids.add(question_id)
            normalized.append({"id": question_id, "question": question_text})
        return normalized

    def _normalized_answers_list(self, answers) -> list:
        valid_ids = {question["id"] for question in self._question_bank}
        normalized = []
        seen_ids = set()
        for raw_entry in list(answers or []):
            if not isinstance(raw_entry, dict):
                continue
            question_id = str(raw_entry.get("question_id") or "").strip()
            if not question_id or question_id not in valid_ids or question_id in seen_ids:
                continue
            answer_text = str(raw_entry.get("answer") or "").strip()
            if not answer_text:
                continue
            normalized.append({"question_id": question_id, "answer": answer_text})
            seen_ids.add(question_id)
        return normalized

    def _answers_map_from_sample(self, sample: dict) -> dict:
        answer_map = {}
        for entry in self._normalized_answers_list(sample.get("answers")):
            answer_map[entry["question_id"]] = entry["answer"]
        return answer_map

    def _answers_list_from_map(self, answer_map: dict) -> list:
        normalized = []
        valid_ids = {question["id"] for question in self._question_bank}
        for question in self._question_bank:
            question_id = question["id"]
            if question_id not in valid_ids:
                continue
            answer_text = str(answer_map.get(question_id) or "").strip()
            if not answer_text:
                continue
            normalized.append({"question_id": question_id, "answer": answer_text})
        return normalized

    def _next_question_id_from_bank(self) -> str:
        max_suffix = 0
        for question in self._question_bank:
            question_id = str(question.get("id") or "")
            if not question_id.startswith("q"):
                continue
            suffix = question_id[1:]
            if suffix.isdigit():
                max_suffix = max(max_suffix, int(suffix))
        return f"q{max_suffix + 1}"
