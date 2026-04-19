"""
Question/Answer mode workflows.
"""

import json

import pytest
from PyQt6.QtCore import QModelIndex


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}


@pytest.mark.gui
def test_question_answer_selection_loads_media_and_answer_editor(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("question_answer")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["question_answer"]
    assert window.tree_model.rowCount() == 1
    assert len(window.dataset_explorer_controller.question_definitions) == 2

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.qa_panel.get_selected_question_id() == "q1"
    assert window.qa_panel.get_answer_text().strip() == "I am fine."
    assert window.qa_panel.answer_editor.isEnabled() is True


@pytest.mark.gui
def test_question_answer_annotate_save_reload_edit_and_persist(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("question_answer")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX["question_answer"]

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    first_answer = "First Q/A answer update from workflow test."
    window.qa_panel.answer_editor.setPlainText(first_answer)
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert any(
        entry.get("question_id") == "q1" and entry.get("answer") == first_answer
        for entry in sample.get("answers", [])
    )

    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_sample = saved.get("data", [])[0]
    assert any(
        entry.get("question_id") == "q1" and entry.get("answer") == first_answer
        for entry in saved_sample.get("answers", [])
    )

    window.dataset_explorer_controller.close_project()
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    reopened_index = window.tree_model.index(0, 0)
    assert reopened_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(reopened_index)
    qtbot.wait(50)

    assert window.qa_panel.get_answer_text().strip() == first_answer


@pytest.mark.gui
def test_question_answer_add_rename_delete_question_updates_bank_and_orphan_answers(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("question_answer")
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)

    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("Who committed the foul?", True),
    )
    plus_tab_idx = window.qa_panel.question_tabs.count() - 1
    assert window.qa_panel.question_tabs.tabText(plus_tab_idx) == "+"
    window.qa_panel.question_tabs.setCurrentIndex(plus_tab_idx)
    qtbot.wait(50)
    assert any(
        entry.get("question") == "Who committed the foul?"
        for entry in window.dataset_explorer_controller.question_definitions
    )

    # Rename q1 via tab context-menu action, then delete it.
    # Deletion must remove orphan answers for q1.
    window.qa_panel.set_questions(
        window.dataset_explorer_controller.question_definitions,
        selected_question_id="q1",
    )
    tab_bar = window.qa_panel.question_tabs.tabBar()
    q1_idx = 0
    for idx in range(window.qa_panel.question_tabs.count()):
        if window.qa_panel.question_tabs.tabText(idx) == "q1":
            q1_idx = idx
            break
    tab_pos = tab_bar.tabRect(q1_idx).center()

    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getText",
        lambda *args, **kwargs: ("How are you doing?", True),
    )
    monkeypatch.setattr(
        "ui.question_answer.QMenu.exec",
        lambda self, *_args, **_kwargs: self.actions()[0],  # Rename Question
    )
    window.qa_panel._on_tab_context_menu_requested(tab_pos)
    qtbot.wait(50)
    assert any(
        entry.get("id") == "q1" and entry.get("question") == "How are you doing?"
        for entry in window.dataset_explorer_controller.question_definitions
    )

    monkeypatch.setattr(
        "ui.question_answer.QMenu.exec",
        lambda self, *_args, **_kwargs: self.actions()[1],  # Delete Question
    )
    window.qa_panel._on_tab_context_menu_requested(tab_pos)
    qtbot.wait(50)
    assert not any(
        entry.get("id") == "q1"
        for entry in window.dataset_explorer_controller.question_definitions
    )

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert not any(
        entry.get("question_id") == "q1"
        for entry in sample.get("answers", [])
    )
