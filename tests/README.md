# GUI Testing Guide (`pytest-qt`)

This folder contains GUI smoke/persistence tests for the PyQt application.

## Goals

- Validate core app lifecycle (`launch`, `import`, `close`).
- Validate data persistence across save/reopen cycles for:
  - Classification
  - Localization
  - Description
  - Dense Description
- Keep tests deterministic by patching file dialogs and avoiding real model inference.

## Structure

- `tests/conftest.py`
  - Configures headless Qt (`QT_QPA_PLATFORM=offscreen`).
  - Adds `annotation_tool/` to `sys.path`.
  - Stubs `opensportslib` import.
  - Isolates `QSettings` to a temp directory per test.
  - Defines shared fixtures (`window`, `synthetic_project_json`).
- `tests/gui/test_core_lifecycle.py`
  - Launch/import/close smoke coverage.
- `tests/gui/test_recent_datasets.py`
  - Recent-datasets persistence/open/remove behavior.
- `tests/gui/test_dataset_editing.py`
  - Add/remove dataset items + save/reopen list persistence.
- `tests/gui/test_workflow_classification.py`
  - Classification annotate/save/reload/edit workflow.
- `tests/gui/test_workflow_localization.py`
  - Localization event/time annotate/save/reload/edit workflow.
  - Localization remove-item and clear-workspace reset workflows.
- `tests/gui/test_workflow_description.py`
  - Description selection/media refresh + annotate/save/reload/edit + remove/clear workspace workflows.
- `tests/gui/test_workflow_dense_description.py`
  - Dense Description event edit/save/reload workflow.
  - Dense item remove/reset and clear-workspace reset workflows.
- `tests/data/`
  - Real media files used by synthetic JSON fixtures (`test_video_1.mp4`, `test_video_2.mp4`).

## Install Dependencies

```bash
pip install pytest pytest-qt PyQt6
```

## Run Tests

Run full lifecycle suite:

```bash
pytest -q tests/gui
```

Run only one workflow:

```bash
pytest -q tests/gui/test_workflow_classification.py
pytest -q tests/gui/test_workflow_localization.py
pytest -q tests/gui/test_workflow_description.py
pytest -q tests/gui/test_workflow_dense_description.py
```

Collection/sanity check:

```bash
pytest --collect-only tests/gui
```

## Current Workflow Inventory

`tests/gui/` currently covers:

- `test_launches_to_welcome_view`
- `test_import_project_routed_flow_all_modes`
- `test_close_project_returns_to_welcome`
- `test_recent_projects_list_updates_after_successful_import`
- `test_recent_project_click_opens_dataset`
- `test_recent_projects_dedupe_order_and_limit`
- `test_recent_projects_failed_open_does_not_add`
- `test_recent_projects_missing_path_removed_on_click`
- `test_recent_projects_remove_button_removes_entry`
- `test_add_five_items_remove_one_save_and_reopen_persists_changes`
- `test_classification_annotate_save_reload_edit_labels_and_persist`
- `test_localization_annotate_save_reload_edit_time_and_persist`
- `test_localization_remove_selected_item_resets_panel_state`
- `test_localization_clear_workspace_resets_panel_and_model`
- `test_description_selection_loads_media_and_refreshes_editor`
- `test_description_annotate_save_reload_edit_and_persist`
- `test_description_remove_selected_item_clears_editor_state`
- `test_description_clear_workspace_resets_editor_and_model`
- `test_dense_description_annotate_save_reload_edit_and_persist`
- `test_dense_description_remove_selected_item_resets_panel_state`
- `test_dense_description_clear_workspace_resets_panel_and_model`

Each function has an inline workflow header comment that explains setup, action, and persistence checks.

## Test Design Notes

- Dialogs are monkeypatched (`QFileDialog`) to avoid manual interaction.
- Playback startup is patched in `window` fixture to avoid multimedia backend issues in headless runs.
- Recent-dataset storage uses `QSettings` and is redirected to a temp folder by an autouse fixture.
- Recents persistence behavior: full deduplicated history is stored; welcome UI shows only newest 5.
- Assertions check both:
  - in-memory state (`AppStateModel` and UI widgets), and
  - serialized JSON output on disk.
- These are integration-style UI tests, not unit tests.

## Troubleshooting

- If tests appear to hang:
  - ensure dialogs are patched in your test path,
  - run single test with `-k <name> -vv`,
  - verify `QT_QPA_PLATFORM=offscreen` is active.
- If imports fail due to ML stack:
  - confirm `tests/conftest.py` is loaded (it installs the `opensportslib` stub).

## Extending the Suite

When adding a new GUI workflow test:

1. Start from `window` + `synthetic_project_json` fixtures in `tests/conftest.py`.
2. Patch all interactive dialogs (`QFileDialog`, optional `QMessageBox` flows).
3. Prefer user-like actions (`qtbot.mouseClick`, widget setters) over direct internal mutation.
4. Assert both runtime state and JSON output after save.
5. Add a one-line workflow header comment above the test function.
