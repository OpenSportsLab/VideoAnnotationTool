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
  - Defines shared fixtures (`window`, `synthetic_project_json`).
- `tests/gui/test_main_window_lifecycle.py`
  - Main lifecycle and persistence workflows.
- `tests/data/`
  - Real media files used by synthetic JSON fixtures (`test_video_1.mp4`, `test_video_2.mp4`).

## Install Dependencies

```bash
pip install pytest pytest-qt PyQt6
```

## Run Tests

Run full lifecycle suite:

```bash
pytest -q tests/gui/test_main_window_lifecycle.py
```

Run only one workflow:

```bash
pytest -q tests/gui/test_main_window_lifecycle.py -k classification
pytest -q tests/gui/test_main_window_lifecycle.py -k localization
pytest -q tests/gui/test_main_window_lifecycle.py -k description
pytest -q tests/gui/test_main_window_lifecycle.py -k dense
```

Collection/sanity check:

```bash
pytest --collect-only tests/gui/test_main_window_lifecycle.py
```

## Current Workflow Inventory

`tests/gui/test_main_window_lifecycle.py` currently covers:

- `test_launches_to_welcome_view`
- `test_import_project_routed_flow_all_modes`
- `test_close_project_returns_to_welcome`
- `test_add_data_save_and_reopen_keeps_new_item`
- `test_classification_annotate_save_reload_edit_labels_and_persist`
- `test_localization_annotate_save_reload_edit_time_and_persist`
- `test_description_annotate_save_reload_edit_and_persist`
- `test_dense_description_annotate_save_reload_edit_and_persist`

Each function has an inline workflow header comment that explains setup, action, and persistence checks.

## Test Design Notes

- Dialogs are monkeypatched (`QFileDialog`) to avoid manual interaction.
- Playback startup is patched in `window` fixture to avoid multimedia backend issues in headless runs.
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
