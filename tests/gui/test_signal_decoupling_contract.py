"""
Signal-based decoupling contract tests.
"""

import inspect
from pathlib import Path

import pytest

from controllers.classification.classification_editor_controller import ClassificationEditorController
from controllers.classification.inference_manager import InferenceManager
from controllers.classification.train_manager import TrainManager
from controllers.dataset_explorer_controller import DatasetExplorerController
from controllers.dense_description.dense_editor_controller import DenseEditorController
from controllers.description.desc_editor_controller import DescEditorController
from controllers.history_manager import HistoryManager
from controllers.localization.loc_inference import LocalizationInferenceManager
from controllers.localization.localization_editor_controller import LocalizationEditorController
from controllers.question_answer.qa_editor_controller import QAEditorController


MODE_TO_TAB_INDEX = {
    "classification": 0,
    "localization": 1,
    "description": 2,
    "dense_description": 3,
    "question_answer": 4,
}


def _open_project(window, monkeypatch, project_json_path: Path):
    monkeypatch.setattr(window.dataset_explorer_controller, "check_and_close_current_project", lambda: True)
    monkeypatch.setattr(
        "controllers.dataset_explorer_controller.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(project_json_path), "JSON Files (*.json)"),
    )
    window.dataset_explorer_controller.import_annotations()


def _select_top_row(window, qtbot, row: int = 0):
    index = window.tree_model.index(row, 0)
    assert index.isValid()
    window.dataset_explorer_panel.tree.setCurrentIndex(index)
    qtbot.wait(50)
    return index


@pytest.mark.gui
def test_controller_constructors_do_not_accept_main_window():
    targets = [
        DatasetExplorerController,
        ClassificationEditorController,
        LocalizationEditorController,
        DescEditorController,
        DenseEditorController,
        QAEditorController,
        HistoryManager,
        InferenceManager,
        TrainManager,
        LocalizationInferenceManager,
    ]
    for cls in targets:
        signature = inspect.signature(cls.__init__)
        assert "main_window" not in signature.parameters, f"{cls.__name__} still accepts main_window"


@pytest.mark.gui
def test_scoped_controller_constructors_do_not_accept_controller_dependencies():
    forbidden = {
        DatasetExplorerController: {
            "main_window",
            "media_controller",
            "center_panel",
            "active_tab_index_provider",
            "status_icon_provider",
            "_legacy_kwargs",
        },
        ClassificationEditorController: {"media_controller"},
        LocalizationEditorController: {"media_controller"},
        DenseEditorController: {"media_controller"},
        QAEditorController: {"media_controller"},
        HistoryManager: {"dataset_explorer_controller"},
    }
    for cls, forbidden_params in forbidden.items():
        signature = inspect.signature(cls.__init__)
        for param in forbidden_params:
            assert param not in signature.parameters, f"{cls.__name__} still accepts {param}"


@pytest.mark.gui
def test_dataset_explorer_constructor_is_strict_panel_tree_model_only():
    signature = inspect.signature(DatasetExplorerController.__init__)
    params = [name for name in signature.parameters if name != "self"]
    assert params == ["panel", "tree_model"]


@pytest.mark.gui
def test_classification_constructor_is_panel_only():
    signature = inspect.signature(ClassificationEditorController.__init__)
    params = [name for name in signature.parameters if name != "self"]
    assert params == ["classification_panel"]


@pytest.mark.gui
def test_localization_constructor_is_panel_only():
    signature = inspect.signature(LocalizationEditorController.__init__)
    params = [name for name in signature.parameters if name != "self"]
    assert params == ["localization_panel"]


@pytest.mark.gui
def test_question_answer_constructor_is_panel_only():
    signature = inspect.signature(QAEditorController.__init__)
    params = [name for name in signature.parameters if name != "self"]
    assert params == ["question_answer_panel"]


@pytest.mark.gui
def test_decoupled_controllers_do_not_use_self_main_access():
    repo_root = Path(__file__).resolve().parents[2]
    targets = [
        repo_root / "annotation_tool" / "controllers" / "dataset_explorer_controller.py",
        repo_root / "annotation_tool" / "controllers" / "classification" / "classification_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "classification" / "inference_manager.py",
        repo_root / "annotation_tool" / "controllers" / "classification" / "train_manager.py",
        repo_root / "annotation_tool" / "controllers" / "localization" / "localization_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "localization" / "loc_inference.py",
        repo_root / "annotation_tool" / "controllers" / "description" / "desc_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "dense_description" / "dense_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "question_answer" / "qa_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "history_manager.py",
    ]
    for path in targets:
        source = path.read_text(encoding="utf-8")
        assert "self.main" not in source, f"Found self.main coupling in {path.name}"


@pytest.mark.gui
def test_explorer_and_editor_controllers_do_not_import_qmediaplayer():
    repo_root = Path(__file__).resolve().parents[2]
    targets = [
        repo_root / "annotation_tool" / "controllers" / "dataset_explorer_controller.py",
        repo_root / "annotation_tool" / "controllers" / "classification" / "classification_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "localization" / "localization_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "description" / "desc_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "dense_description" / "dense_editor_controller.py",
        repo_root / "annotation_tool" / "controllers" / "question_answer" / "qa_editor_controller.py",
    ]
    for path in targets:
        source = path.read_text(encoding="utf-8")
        assert "QMediaPlayer" not in source, f"Found QMediaPlayer usage in {path.name}"


@pytest.mark.gui
def test_dataset_explorer_no_longer_exposes_mode_mutation_apply_methods():
    repo_root = Path(__file__).resolve().parents[2]
    source = (repo_root / "annotation_tool" / "controllers" / "dataset_explorer_controller.py").read_text(
        encoding="utf-8"
    )
    forbidden = [
        "def apply_classification_",
        "def apply_localization_",
        "def apply_description_caption_save",
        "def apply_dense_event_",
    ]
    for snippet in forbidden:
        assert snippet not in source


@pytest.mark.gui
def test_mainwindow_connect_signals_uses_direct_controller_wiring_contract():
    repo_root = Path(__file__).resolve().parents[2]
    main_window_source = (repo_root / "annotation_tool" / "main_window.py").read_text(encoding="utf-8")

    required_snippets = [
        "self.dataset_explorer_controller = DatasetExplorerController(",
        "panel=self.dataset_explorer_panel",
        "tree_model=self.tree_model",
        "self.dataset_explorer_controller.set_status_icons(self.done_icon, self.empty_icon)",
        "self.right_tabs.currentChanged.connect(self.dataset_explorer_controller.set_active_mode)",
        "self.right_tabs.currentChanged.connect(self.dataset_explorer_controller.handle_active_mode_changed)",
        "self.right_tabs.currentChanged.connect(self.classification_editor_controller.on_mode_changed)",
        "self.right_tabs.currentChanged.connect(self.localization_editor_controller.on_mode_changed)",
        "self.right_tabs.currentChanged.connect(self.desc_editor_controller.on_mode_changed)",
        "self.right_tabs.currentChanged.connect(self.dense_editor_controller.on_mode_changed)",
        "self.right_tabs.currentChanged.connect(self.qa_editor_controller.on_mode_changed)",
        "self.dataset_explorer_controller.statusMessageRequested.connect(self.show_temp_msg)",
        "self.dataset_explorer_controller.questionBankChanged.connect(",
        "self.dataset_explorer_controller.qaSaveRequested.connect(self.qa_editor_controller.save_current_answers)",
        "self.history_manager.refreshUiAfterUndoRedoRequested.connect(self.refresh_ui_after_undo_redo)",
        "self.classification_editor_controller.manualAnnotationSaveRequested.connect(",
        "self.history_manager.execute_classification_manual_annotation",
        "self.localization_editor_controller.locEventModRequested.connect(",
        "self.history_manager.execute_localization_event_mod",
        "self.desc_editor_controller.captionsUpdateRequested.connect(",
        "self.history_manager.execute_sample_captions_update",
        "self.dense_editor_controller.denseEventAddRequested.connect(",
        "self.history_manager.execute_dense_event_add",
        "self.qa_editor_controller.qaQuestionAddRequested.connect(",
        "self.history_manager.execute_qa_question_add",
        "self.qa_editor_controller.qaAnswersUpdateRequested.connect(",
        "self.history_manager.execute_qa_answers_update",
        "self.history_manager.questionBankRefreshRequested.connect(",
        "self.dataset_explorer_controller.headerDraftMutationRequested.connect(",
        "self.history_manager.execute_header_draft_update",
        "self.history_manager.datasetRestoreRequested.connect(",
    ]
    for snippet in required_snippets:
        assert snippet in main_window_source


@pytest.mark.gui
def test_tab_change_updates_all_controller_mode_states_and_reemits_selection(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("mixed", item_count=1)
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    selected_id = window.dataset_explorer_controller.current_selected_sample_id
    assert selected_id == "clip_1"

    emitted_data_ids = []
    window.dataset_explorer_controller.dataSelected.connect(emitted_data_ids.append)

    target_mode = MODE_TO_TAB_INDEX["dense_description"]
    window.right_tabs.setCurrentIndex(target_mode)
    qtbot.wait(50)

    assert window.classification_editor_controller._active_mode_index == target_mode
    assert window.localization_editor_controller._active_mode_index == target_mode
    assert window.desc_editor_controller._active_mode_index == target_mode
    assert window.dense_editor_controller._active_mode_index == target_mode
    assert window.qa_editor_controller._active_mode_index == target_mode
    assert emitted_data_ids
    assert emitted_data_ids[-1] == selected_id


@pytest.mark.gui
def test_controller_shell_signals_route_to_mainwindow_status_and_save_state(
    window,
    monkeypatch,
    qtbot,
    synthetic_project_json,
):
    project_json_path = synthetic_project_json("classification")
    _open_project(window, monkeypatch, project_json_path)
    _select_top_row(window, qtbot, 0)

    window.dataset_explorer_controller.is_data_dirty = False
    window.update_save_export_button_state()
    assert window.action_save.isEnabled() is False

    window.dataset_explorer_controller.is_data_dirty = True
    window.classification_editor_controller.saveStateRefreshRequested.emit()
    qtbot.wait(20)
    assert window.action_save.isEnabled() is True

    window.classification_editor_controller.statusMessageRequested.emit("Signal Route", "status wired", 1000)
    qtbot.wait(20)
    assert "Signal Route" in window.statusBar().currentMessage()
