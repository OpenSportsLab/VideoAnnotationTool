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
def test_question_answer_selection_loads_media_and_answer_list(
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
    assert window.qa_panel.question_list.item(0).text() == "How are you?"
    assert "How are you?" in window.qa_editor_controller._question_catalog
    assert window.qa_panel.answer_list.currentRow() == 0
    assert window.qa_panel.answer_list.item(0).text() == "I am fine."
    assert window.qa_panel.add_answer_button.text() == "Answer"
    assert window.qa_panel.add_answer_button.isEnabled() is True


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
    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: (first_answer, True),
    )
    window.qa_panel._on_answer_item_double_clicked(window.qa_panel.answer_list.item(0))
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

    assert window.qa_panel.answer_list.item(0).text() == first_answer


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

    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("Who committed the foul?", True),
    )
    window.qa_panel.add_question_button.click()
    qtbot.wait(50)
    assert window.qa_panel.question_list.currentRow() == 1
    assert window.qa_panel.question_list.currentItem().text() == "Who committed the foul?"

    answer_dialog_values = iter(["The defender.", "The player in blue."])
    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: (next(answer_dialog_values), True),
    )
    window.qa_panel.add_answer_button.click()
    qtbot.wait(350)

    window.qa_panel.add_answer_button.click()
    qtbot.wait(350)
    assert window.qa_panel.answer_list.currentRow() == 1

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert {
        entry.get("question"): entry.get("answers")
        for entry in sample.get("answers", [])
    }["Who committed the foul?"] == ["The defender.", "The player in blue."]


@pytest.mark.gui
def test_question_answer_double_click_edits_and_context_menu_removes_question_group(
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
        "controllers.question_answer.qa_editor_controller.QInputDialog.getItem",
        lambda *args, **kwargs: ("How are you doing?", True),
    )
    question_pos = window.qa_panel.question_list.visualItemRect(
        window.qa_panel.question_list.item(0)
    ).center()
    window.qa_panel._on_question_item_double_clicked(window.qa_panel.question_list.item(0))
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert sample.get("answers") == [
        {"question": "How are you doing?", "answers": ["I am fine."]}
    ]

    monkeypatch.setattr(
        "ui.question_answer.QMenu.exec",
        lambda self, *_args, **_kwargs: self.actions()[1],
    )
    window.qa_panel._on_question_context_menu_requested(question_pos)
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert "answers" not in sample


@pytest.mark.gui
def test_question_answer_double_click_and_context_menu_edit_answers(
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
        "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("Edited by double click.", True),
    )
    window.qa_panel._on_answer_item_double_clicked(window.qa_panel.answer_list.item(0))
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert sample.get("answers") == [
        {"question": "How are you?", "answers": ["Edited by double click."]}
    ]

    monkeypatch.setattr(
        "controllers.question_answer.qa_editor_controller.QInputDialog.getMultiLineText",
        lambda *args, **kwargs: ("Edited by context menu.", True),
    )
    monkeypatch.setattr(
        "ui.question_answer.QMenu.exec",
        lambda self, *_args, **_kwargs: self.actions()[0],
    )
    answer_pos = window.qa_panel.answer_list.visualItemRect(
        window.qa_panel.answer_list.item(0)
    ).center()
    window.qa_panel._on_answer_context_menu_requested(answer_pos)
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert sample.get("answers") == [
        {"question": "How are you?", "answers": ["Edited by context menu."]}
    ]

    monkeypatch.setattr(
        "ui.question_answer.QMenu.exec",
        lambda self, *_args, **_kwargs: self.actions()[1],
    )
    window.qa_panel._on_answer_context_menu_requested(answer_pos)
    qtbot.wait(350)

    sample = window.dataset_explorer_controller.get_sample("clip_1")
    assert sample is not None
    assert "answers" not in sample
