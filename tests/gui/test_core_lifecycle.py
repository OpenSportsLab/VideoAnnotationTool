"""
Core GUI lifecycle smoke tests for `VideoAnnotationWindow`.
"""

import pytest
from PyQt6.QtCore import Qt


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
}


@pytest.mark.gui
# Workflow: App startup should land on welcome screen with project UI disabled and no dataset loaded.
def test_launches_to_welcome_view(window):
    assert window.center_stack.currentIndex() == 0
    assert window.data_dock.isEnabled() is False
    assert window.editor_dock.isEnabled() is False
    assert window.model.json_loaded is False


@pytest.mark.gui
@pytest.mark.parametrize("mode", list(MODE_TO_TAB_INDEX.keys()))
# Workflow: For each mode, import a synthetic JSON via routed file dialog and verify mode/view/tree state.
def test_import_project_routed_flow_all_modes(window, monkeypatch, synthetic_project_json, mode):
    project_json_path = synthetic_project_json(mode)

    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.router.import_annotations()

    assert window.model.json_loaded is True
    assert window.model.current_json_path == str(project_json_path)
    assert window.center_stack.currentIndex() == 1
    assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX[mode]
    assert window.tree_model.rowCount() == 1


# @pytest.mark.gui
# @pytest.mark.parametrize("mode", list(MODE_TO_TAB_INDEX.keys()))
# # Workflow: Create a new project through router dialog flow for each mode and verify workspace/tab/model state.
# def test_create_project_routed_flow_all_modes(window, monkeypatch, mode):
#     class _FakeProjectTypeDialog:
#         def __init__(self, parent=None):
#             self.selected_mode = mode

#         def exec(self):
#             return True

#     class _FakeClassificationTypeDialog:
#         def __init__(self, parent=None):
#             self.is_multi_view = False

#         def exec(self):
#             return True

#     monkeypatch.setattr("controllers.router.ProjectTypeDialog", _FakeProjectTypeDialog)
#     monkeypatch.setattr("ui.dialogs.ClassificationTypeDialog", _FakeClassificationTypeDialog)

#     window.router.create_new_project_flow()

#     assert window.model.json_loaded is True
#     assert window.model.current_json_path is None
#     assert window.center_stack.currentIndex() == 1
#     assert window.right_tabs.currentIndex() == MODE_TO_TAB_INDEX[mode]


@pytest.mark.gui
# Workflow: Create/load a project, trigger close flow, and verify full reset back to welcome view.
def test_close_project_returns_to_welcome(window, monkeypatch):
    window.dataset_explorer_controller.create_new_project("localization")
    assert window.model.json_loaded is True

    monkeypatch.setattr(window, "check_and_close_current_project", lambda: True)

    window.router.close_project()

    assert window.model.json_loaded is False
    assert window.center_stack.currentIndex() == 0
    assert window.tree_model.rowCount() == 0


@pytest.mark.gui
# Workflow: Dataset Explorer Prev/Next Sample buttons should move current top-level dataset selection.
def test_dataset_explorer_prev_next_sample_buttons_navigate_rows(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification", item_count=3)
    monkeypatch.setattr(
        "controllers.router.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )

    window.router.import_annotations()
    assert window.tree_model.rowCount() == 3

    tree = window.dataset_explorer_panel.tree
    first_index = window.tree_model.index(0, 0)
    tree.setCurrentIndex(first_index)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0

    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 1

    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 2

    # Boundary: next on last row should keep selection unchanged.
    qtbot.mouseClick(window.dataset_explorer_panel.btn_next_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 2

    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 1

    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0

    # Boundary: prev on first row should keep selection unchanged.
    qtbot.mouseClick(window.dataset_explorer_panel.btn_prev_sample, Qt.MouseButton.LeftButton)
    qtbot.wait(50)
    assert tree.currentIndex().row() == 0


@pytest.mark.gui
# Workflow: Closing a loaded-but-clean project should not open a confirmation popup.
def test_close_project_when_clean_skips_confirmation_popup(window, monkeypatch):
    window.dataset_explorer_controller.create_new_project("localization")
    assert window.model.json_loaded is True
    window.model.is_data_dirty = False

    stop_calls = {"count": 0}
    monkeypatch.setattr(
        window.media_controller,
        "stop",
        lambda: stop_calls.__setitem__("count", stop_calls["count"] + 1),
    )
    # If a popup is shown unexpectedly, fail the test.
    monkeypatch.setattr(
        "main_window.QMessageBox.exec",
        lambda self: (_ for _ in ()).throw(AssertionError("Confirmation popup should not be shown")),
    )

    should_close = window.check_and_close_current_project()
    assert should_close is True
    assert stop_calls["count"] == 1


# @pytest.mark.gui
# # Workflow: If user cancels close flow, the current workspace remains open and loaded.
# def test_close_project_cancel_keeps_workspace_open(window, monkeypatch):
#     window.dataset_explorer_controller.create_new_project("localization")
#     assert window.model.json_loaded is True
#     assert window.center_stack.currentIndex() == 1

#     monkeypatch.setattr(window, "check_and_close_current_project", lambda: False)
#     window.router.close_project()

#     assert window.model.json_loaded is True
#     assert window.center_stack.currentIndex() == 1


# @pytest.mark.gui
# # Workflow: Quit action should route to dataset close when a project is loaded.
# def test_action_quit_closes_dataset_when_loaded(window, monkeypatch):
#     window.dataset_explorer_controller.create_new_project("description")
#     assert window.model.json_loaded is True

#     close_calls = {"count": 0}
#     window_close_calls = {"count": 0}
#     monkeypatch.setattr(
#         window.router,
#         "close_project",
#         lambda: close_calls.__setitem__("count", close_calls["count"] + 1),
#     )
#     monkeypatch.setattr(
#         window,
#         "close",
#         lambda: window_close_calls.__setitem__("count", window_close_calls["count"] + 1),
#     )

#     window.action_quit.trigger()

#     assert close_calls["count"] == 1
#     assert window_close_calls["count"] == 0


# @pytest.mark.gui
# # Workflow: Quit action should close the app window when no project is loaded.
# def test_action_quit_closes_window_when_unloaded(window, monkeypatch):
#     window.model.json_loaded = False
#     close_calls = {"count": 0}
#     monkeypatch.setattr(window.router, "close_project", lambda: None)
#     monkeypatch.setattr(
#         window,
#         "close",
#         lambda: close_calls.__setitem__("count", close_calls["count"] + 1),
#     )

#     window.action_quit.trigger()
#     assert close_calls["count"] == 1


# @pytest.mark.gui
# # Workflow: check_and_close_current_project should return False when dialog is canceled.
# def test_check_and_close_current_project_cancel_returns_false(window, monkeypatch):
#     window.model.json_loaded = True
#     window.model.is_data_dirty = True

#     def _fake_exec(self):
#         no_button = next(btn for btn in self.buttons() if btn.text() == "No")
#         no_button.click()
#         return 0

#     monkeypatch.setattr("main_window.QMessageBox.exec", _fake_exec)
#     stopped = {"count": 0}
#     monkeypatch.setattr(window.media_controller, "stop", lambda: stopped.__setitem__("count", stopped["count"] + 1))

#     should_close = window.check_and_close_current_project()
#     assert should_close is False
#     assert stopped["count"] == 0
