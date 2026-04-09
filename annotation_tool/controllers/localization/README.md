# Localization Controllers

## Role
Implements Localization (action spotting) behavior, including schema management, event CRUD, and smart inference workflows.

## Architecture Context
- `LocalizationEditorController` orchestrates Localization panel behavior.
- Receives selection context from `DatasetExplorerController`.
- Emits schema/event mutation intents to `HistoryManager`.
- Uses `LocalizationInferenceManager` for smart inference execution.

## Public Surface
### Class
- `LocalizationEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
- `locHeadAddRequested(str)`
- `locHeadRenameRequested(str, str)`
- `locHeadDeleteRequested(str)`
- `locLabelAddRequested(str, str, str, int, bool)`
- `locLabelRenameRequested(str, str, str)`
- `locLabelDeleteRequested(str, str)`
- `locEventAddRequested(str, dict)`
- `locEventModRequested(str, dict, dict)`
- `locEventDelRequested(str, dict, int)`

### Helper
- `LocalizationInferenceManager`

## Key Functions and Responsibilities
- `setup_connections()`
  - Wires tabs/tables/smart widgets to controller actions.
- `on_mode_changed(index)`
  - Refreshes markers/table according to active sub-tab.
- `on_data_selected(data_id)`
  - Loads selected sample context into Localization panel.
- Head/label functions:
  - `_on_head_added`, `_on_head_renamed`, `_on_head_deleted`
  - `_on_label_add_req`, `_on_label_rename_req`, `_on_label_delete_req`
- Event functions:
  - `_on_spotting_triggered`, `_on_annotation_modified`, `_on_delete_single_annotation`
- Smart flows:
  - `_run_localization_inference`, `_confirm_smart_events`, `_clear_smart_events`

## Business Rules
- Schema operations enforce duplicate/name validity checks.
- Event modify/delete requires event existence and valid selection.
- Label add flow can optionally inject an event at current playback time.
- Pause/resume around modal label dialogs is signal-driven.

## Conventions
- Emit mutation intents; do not apply persisted mutation policy locally.
- Keep marker/table display in controller, widget layout in UI package.
- Respect no-op guard behavior for unchanged edits.

## Interactions
- Inbound:
  - `DatasetExplorerController.dataSelected -> on_data_selected`
  - `MediaController.playbackStateChanged -> on_playback_state_changed`
- Outbound:
  - Mutation signals -> `HistoryManager.execute_*`
  - Status/save/item refresh -> `main_window` shell handlers

## Tests
- `tests/gui/test_workflow_localization.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Event identity:
  localization table edits rely on old/new event matching; preserve deterministic event keys (`head`, `label`, `position_ms`).
- Dialog flows:
  keep pause/resume signal toggling symmetric (toggle before + after) when modal input is used.
- Schema edits and event edits are coupled:
  head/label renames must keep existing events coherent.
- Smart tab and hand tab behavior differs; when changing tab logic, verify marker behavior in both.
- Always keep no-op checks for unchanged event modifications.
