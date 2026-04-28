import copy

from PyQt6.QtCore import QObject, QTimer, pyqtSignal


class QAEditorController(QObject):
    """
    Question/Answer editor controller.
    Owns per-sample grouped question/answer editing.
    """

    statusMessageRequested = pyqtSignal(str, str, int)
    qaAnswersUpdateRequested = pyqtSignal(str, object)

    def __init__(self, question_answer_panel):
        super().__init__()
        self.question_answer_panel = question_answer_panel

        self._active_mode_index = 0
        self._project_enabled = False
        self._selection_enabled = False
        self._suspend_autosave = False

        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answer_groups = []
        self._selected_group_index = -1
        self._selected_answer_index = -1

        self._autosave_timer = QTimer(self.question_answer_panel)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(250)
        self._autosave_timer.timeout.connect(self.save_current_answers)

    def setup_connections(self):
        self.question_answer_panel.questionGroupAddRequested.connect(
            self._on_add_question_group_requested
        )
        self.question_answer_panel.questionGroupDeleteRequested.connect(
            self._on_delete_question_group_requested
        )
        self.question_answer_panel.questionGroupSelectionChanged.connect(
            self._on_question_group_selection_changed
        )
        self.question_answer_panel.questionTextChanged.connect(self._on_question_text_changed)
        self.question_answer_panel.answerAddRequested.connect(self._on_add_answer_requested)
        self.question_answer_panel.answerDeleteRequested.connect(self._on_delete_answer_requested)
        self.question_answer_panel.answerSelectionChanged.connect(self._on_answer_selection_changed)
        self.question_answer_panel.answerTextChanged.connect(self._on_answer_text_changed)

    def on_mode_changed(self, index: int):
        self._active_mode_index = index

    def set_project_enabled(self, enabled: bool):
        self._project_enabled = bool(enabled)
        self._update_editor_enabled()

    def set_sample_selection_enabled(self, enabled: bool):
        self._selection_enabled = bool(enabled)
        self._update_editor_enabled()

    def reset_ui(self):
        self._autosave_timer.stop()
        self._project_enabled = False
        self._selection_enabled = False
        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answer_groups = []
        self._selected_group_index = -1
        self._selected_answer_index = -1

        self._set_question_groups([])
        self._update_editor_enabled()

    def on_selected_sample_changed(self, sample):
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self.save_current_answers()

        self.current_sample_id = ""
        self._current_sample_snapshot = {}
        self._answer_groups = []
        self._selected_group_index = -1
        self._selected_answer_index = -1

        if isinstance(sample, dict):
            sample_id = str(sample.get("id") or "")
            if sample_id:
                self.current_sample_id = sample_id
                self._current_sample_snapshot = copy.deepcopy(sample)
                self._answer_groups = self._normalize_answers_payload(sample.get("answers"))

        if self._answer_groups:
            self._selected_group_index = 0
            self._selected_answer_index = 0 if self._answer_groups[0].get("answers") else -1

        self._set_question_groups(self._answer_groups)
        self._update_editor_enabled()

    def _on_add_question_group_requested(self):
        if not self.current_sample_id:
            return
        self._answer_groups.append({"question": "", "answers": [""]})
        self._selected_group_index = len(self._answer_groups) - 1
        self._selected_answer_index = 0
        self._set_question_groups(self._answer_groups)
        self._update_editor_enabled()

    def _on_delete_question_group_requested(self):
        group_index = self._selected_group_index
        if not self._valid_group_index(group_index):
            return

        self._answer_groups.pop(group_index)
        if self._answer_groups:
            self._selected_group_index = min(group_index, len(self._answer_groups) - 1)
            answers = self._answer_groups[self._selected_group_index].get("answers", [])
            self._selected_answer_index = 0 if answers else -1
        else:
            self._selected_group_index = -1
            self._selected_answer_index = -1
        self._set_question_groups(self._answer_groups)
        self._start_autosave()
        self._update_editor_enabled()

    def _on_question_group_selection_changed(self, index: int):
        if self._suspend_autosave:
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self.save_current_answers()

        self._selected_group_index = int(index)
        if self._valid_group_index(self._selected_group_index):
            answers = self._answer_groups[self._selected_group_index].get("answers", [])
            self._selected_answer_index = 0 if answers else -1
            self._sync_editors_from_selection()
        else:
            self._selected_answer_index = -1
            self._sync_editors_from_selection()
        self._update_editor_enabled()

    def _on_question_text_changed(self):
        if self._suspend_autosave or not self.current_sample_id:
            return
        if not self._valid_group_index(self._selected_group_index):
            return

        self._answer_groups[self._selected_group_index]["question"] = (
            self.question_answer_panel.get_question_text()
        )
        self.question_answer_panel.refresh_question_label(
            self._answer_groups[self._selected_group_index],
            self._selected_group_index,
        )
        self._start_autosave()

    def _on_add_answer_requested(self):
        if not self._valid_group_index(self._selected_group_index):
            return
        answers = self._answer_groups[self._selected_group_index].setdefault("answers", [])
        answers.append("")
        self._selected_answer_index = len(answers) - 1
        self._set_answer_rows(answers)
        self._update_editor_enabled()

    def _on_delete_answer_requested(self):
        if not self._valid_answer_index(self._selected_group_index, self._selected_answer_index):
            return
        answers = self._answer_groups[self._selected_group_index].setdefault("answers", [])
        answers.pop(self._selected_answer_index)
        if answers:
            self._selected_answer_index = min(self._selected_answer_index, len(answers) - 1)
        else:
            self._selected_answer_index = -1
        self._set_answer_rows(answers)
        self._start_autosave()
        self._update_editor_enabled()

    def _on_answer_selection_changed(self, index: int):
        if self._suspend_autosave:
            return
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self.save_current_answers()

        self._selected_answer_index = int(index)
        self._sync_answer_editor_from_selection()
        self._update_editor_enabled()

    def _on_answer_text_changed(self):
        if self._suspend_autosave or not self.current_sample_id:
            return
        if not self._valid_answer_index(self._selected_group_index, self._selected_answer_index):
            return

        answers = self._answer_groups[self._selected_group_index].setdefault("answers", [])
        answers[self._selected_answer_index] = self.question_answer_panel.get_answer_text()
        self.question_answer_panel.refresh_answer_label(
            answers[self._selected_answer_index],
            self._selected_answer_index,
        )
        self._start_autosave()

    def save_current_answers(self):
        if not self.current_sample_id:
            return False

        new_answers = self._normalize_answers_payload(self._answer_groups)
        old_answers = self._normalize_answers_payload(self._current_sample_snapshot.get("answers"))
        if old_answers == new_answers:
            return False

        self.qaAnswersUpdateRequested.emit(self.current_sample_id, copy.deepcopy(new_answers))
        if new_answers:
            self._current_sample_snapshot["answers"] = copy.deepcopy(new_answers)
        else:
            self._current_sample_snapshot.pop("answers", None)
        return True

    def _start_autosave(self):
        if self.current_sample_id:
            self._autosave_timer.start()

    def _set_question_groups(self, groups):
        self._suspend_autosave = True
        try:
            self.question_answer_panel.set_question_groups(
                groups,
                selected_group_index=self._selected_group_index,
                selected_answer_index=self._selected_answer_index,
            )
        finally:
            self._suspend_autosave = False

    def _set_answer_rows(self, answers):
        self._suspend_autosave = True
        try:
            self.question_answer_panel.set_answer_rows(
                answers,
                selected_answer_index=self._selected_answer_index,
            )
        finally:
            self._suspend_autosave = False

    def _sync_editors_from_selection(self):
        self._suspend_autosave = True
        try:
            if self._valid_group_index(self._selected_group_index):
                group = self._answer_groups[self._selected_group_index]
                self.question_answer_panel.set_question_text(group.get("question", ""))
                self.question_answer_panel.set_answer_rows(
                    group.get("answers", []),
                    selected_answer_index=self._selected_answer_index,
                )
            else:
                self.question_answer_panel.set_question_text("")
                self.question_answer_panel.set_answer_rows([], selected_answer_index=-1)
        finally:
            self._suspend_autosave = False

    def _sync_answer_editor_from_selection(self):
        self._suspend_autosave = True
        try:
            if self._valid_answer_index(self._selected_group_index, self._selected_answer_index):
                answer_text = self._answer_groups[self._selected_group_index]["answers"][
                    self._selected_answer_index
                ]
                self.question_answer_panel.set_answer_text(answer_text)
            else:
                self.question_answer_panel.set_answer_text("")
        finally:
            self._suspend_autosave = False

    def _update_editor_enabled(self):
        editor_enabled = bool(
            self._project_enabled and self._selection_enabled and self.current_sample_id
        )
        has_group = self._valid_group_index(self._selected_group_index)
        has_answer = self._valid_answer_index(self._selected_group_index, self._selected_answer_index)
        self.question_answer_panel.set_controls_enabled(
            editor_enabled=editor_enabled,
            has_group=has_group,
            has_answer=has_answer,
        )

    def _valid_group_index(self, index: int) -> bool:
        try:
            index = int(index)
        except Exception:
            return False
        return 0 <= index < len(self._answer_groups)

    def _valid_answer_index(self, group_index: int, answer_index: int) -> bool:
        try:
            group_index = int(group_index)
            answer_index = int(answer_index)
        except Exception:
            return False
        if not self._valid_group_index(group_index):
            return False
        answers = self._answer_groups[group_index].get("answers")
        return isinstance(answers, list) and 0 <= answer_index < len(answers)

    @classmethod
    def _normalize_answers_payload(cls, answers) -> list:
        normalized = []
        index_by_question = {}
        for raw_group in list(answers or []):
            if not isinstance(raw_group, dict) or "question_id" in raw_group:
                continue

            question = str(raw_group.get("question") or "").strip()
            if not question:
                continue

            raw_answers = raw_group.get("answers")
            if not isinstance(raw_answers, list):
                continue

            answer_texts = []
            for raw_answer in raw_answers:
                answer_text = str(raw_answer or "").strip()
                if answer_text:
                    answer_texts.append(answer_text)
            if not answer_texts:
                continue

            existing_index = index_by_question.get(question)
            if existing_index is None:
                index_by_question[question] = len(normalized)
                normalized.append({"question": question, "answers": answer_texts})
            else:
                normalized[existing_index]["answers"].extend(answer_texts)
        return normalized
