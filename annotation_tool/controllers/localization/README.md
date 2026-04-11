# Localization Controllers

## Role
Implements Localization (action spotting) behavior, including schema management, event CRUD, and per-head smart inference workflows.

## Architecture Context
- `LocalizationEditorController` orchestrates Localization panel behavior.
- Constructor takes only the localization panel object.
- Controller does not own dataset model state (`self.model` is not used).
- Runtime sample/schema/action-list context is supplied through signal-slot wiring in `MainWindow.connect_signals()`.
- Emits schema/event mutation intents to `HistoryManager`.
- Uses `LocalizationInferenceManager` for smart inference execution.
- Smart inference resolves a dedicated `annotation_tool/loc_config.yaml` template, clips the requested time range for inference, and maps predictions back onto the selected head.
- Emits media seek/marker/toggle intents instead of mutating media widgets directly.
- OpenSportsLib compatibility matters for Localization: `opensportslib==0.1.0` reintroduced a hard DALI-backed localization path, while the `smart-annotation` feature relies on the older non-DALI localization implementation from `opensportslib==0.0.1.dev18`.

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
- `locEventsSetRequested(str, object)`
- `mediaSeekRequested(int)`
- `markersUpdateRequested(object)`
- `mediaTogglePlaybackRequested()`

### Helper
- `LocalizationInferenceManager`

## Key Functions and Responsibilities
- `setup_connections()`
  - Wires spotting tabs/table actions to controller behavior.
- `on_selected_sample_changed(sample)`
  - Loads selected sample snapshot into Localization panel.
- `on_schema_context_changed(schema)`
  - Rebuilds schema-driven localization controls from runtime schema context.
- Head/label functions:
  - `_on_head_added`, `_on_head_renamed`, `_on_head_deleted`
  - `_on_label_add_req`, `_on_label_rename_req`, `_on_label_delete_req`
- Event functions:
  - `_on_spotting_triggered`, `_on_annotation_modified`, `_on_delete_single_annotation`
- Smart flows:
  - `_on_head_smart_inference_requested`, `_on_inference_success`, `_on_confirm_single_annotation`, `_on_reject_single_annotation`

## Business Rules
- Schema operations enforce duplicate/name validity checks.
- Event modify/delete requires event existence and valid selection.
- Label add flow can optionally inject an event at current playback time.
- Pause/resume around modal label dialogs is signal-driven.
- Smart inference writes directly into canonical `events[]` with `confidence_score`.
- Smart inference startup passes the selected head labels and input fps into `LocalizationInferenceManager`; the worker should not rely on hardcoded `ball_action` schema classes from config.
- If localization inference starts failing with `nvidia.dali` / `cupy` import errors on macOS, verify the environment is using the non-DALI OpenSportsLib build rather than `0.1.0`.
- Confirming (or manually editing) an inferred row removes `confidence_score` only.
- Table confidence-cell confirmation prompt supports `Yes` (confirm), `No` (reject), `Cancel` (no-op).
- Rejecting an inferred row deletes the smart-inferred event row.
- Unknown predicted labels are mapped via popup per inference run.

## Conventions
- Emit mutation intents; do not apply persisted mutation policy locally.
- Keep marker/table display in controller, widget layout in UI package.
- Timeline markers should reuse the same label-color mapping as the Localization table rows.
- Respect no-op guard behavior for unchanged edits.
- Keep constructor boundary clean: panel-only constructor.

## Interactions
- Inbound:
  - `DatasetExplorerController.sampleSelectionChanged -> on_selected_sample_changed`
  - `DatasetExplorerController.schemaContextChanged -> on_schema_context_changed`
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
