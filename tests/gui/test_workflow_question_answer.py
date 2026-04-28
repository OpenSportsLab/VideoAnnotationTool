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
    assert "questions" not in window.dataset_explorer_controller.dataset_json

    first_index = window.tree_model.index(0, 0)
    assert first_index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(QModelIndex())
    window.dataset_explorer_panel.tree.setCurrentIndex(first_index)
    qtbot.wait(50)

    assert window.qa_panel.question_list.currentRow() == 0
    assert window.qa_panel.get_question_text().strip() == "How are you?"
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
    assert sample.get("answers") == [{"question": "How are you?", "answers": [first_answer]}]

    window.dataset_explorer_controller.save_project()
    saved = json.loads(project_json_path.read_text(encoding="utf-8"))
    saved_sample = saved.get("data", [])[0]
    assert "questions" not in saved
    assert saved_sample.get("answers") == [{"question": "How are you?", "answers": [first_answer]}]

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
def test_question_answer_add_question_group_and_multiple_answers(
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

    window.qa_panel.add_question_button.click()
    qtbot.wait(50)
    assert window.qa_panel.question_list.currentRow() == 1

    window.qa_panel.question_editor.setPlainText("Who committed the foul?")
    window.qa_panel.answer_editor.setPlainText("The defender.")
    qtbot.wait(350)

    window.qa_panel.add_answer_button.click()
    qtbot.wait(50)
    assert window.qa_panel.answer_list.currentRow() == 1
    window.qa_panel.answer_editor.setPlainText("The player in blue.")
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert {
        entry.get("question"): entry.get("answers")
        for entry in sample.get("answers", [])
    }["Who committed the foul?"] == ["The defender.", "The player in blue."]
