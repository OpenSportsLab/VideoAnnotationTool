# Localization Controllers

## Role
Implements Localization (action spotting) behavior, including schema management,
event CRUD, and transient prediction review.

The shared local/remote path is owned by the central inference controller.
Remote range inputs may be clipped before upload and returned positions are
offset back onto the original sample timeline.

## Architecture Context
- `LocalizationEditorController` orchestrates Localization panel behavior.
- Constructor takes only the localization panel object.
- Controller does not own dataset model state (`self.model` is not used).
- Runtime sample/schema/action-list context is supplied through signal-slot wiring in `MainWindow.connect_signals()`.
- Emits schema/event mutation intents to `HistoryManager`.
- Local/Remote execution is owned by the central `InferenceController`; local
  execution calls OpenSportsLib directly through its provider.
- Local execution resolves device and loader capabilities in a temporary
  config. Missing CUDA selects CPU, and CPU or missing DALI changes DALI video
  datasets to their OpenCV equivalents without editing the registered model
  config.
- Emits media seek/marker/toggle intents instead of mutating media widgets directly.

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

## Key Functions and Responsibilities
- `setup_connections()`
  - Wires spotting tabs/table actions to controller behavior.
- `on_selected_sample_changed(sample)`
  - Loads selected sample snapshot into Localization panel.
- `on_timeline_origin_changed(sample_id, origin_utc)`
  - Projects authoritative UTC events onto the active sample timeline and gives
    the table its UTC formatting/editing context.
- `on_schema_context_changed(schema)`
  - Rebuilds schema-driven localization controls from runtime schema context.
- Head/label functions:
  - `_on_head_added`, `_on_head_renamed`, `_on_head_deleted`
  - `_on_label_add_req`, `_on_label_rename_req`, `_on_label_delete_req`
- Event functions:
  - `_on_spotting_triggered`, `_on_annotation_modified`, `_on_delete_single_annotation`
- Prediction flows:
  - `_request_shared_inference`, `apply_shared_inference_result`,
    `_on_confirm_single_annotation`, `_on_reject_single_annotation`

## Business Rules
- Schema operations enforce duplicate/name validity checks.
- Event modify/delete requires event existence and valid selection.
- Label add flow can optionally inject an event at current playback time.
- Pause/resume around modal label dialogs is signal-driven.
- Inference results remain transient and are combined with canonical events only for display.
- New, moved, and inferred events write `timestamp_utc` plus `position_ms` when
  a genuine sample origin is available; relative-only samples keep `position_ms`.
- The shared run dialog supplies head, labels, range, model, and provider details.
- Runtime fallback supports both legacy (`dali`, `DATA.test.type`) and canonical
  (`DATA.common.runtime.loader_backend`) OpenSportsLib configuration shapes.
- Accepting adds a metadata-free event; rejecting a transient prediction is
  non-mutating. Rejecting a confidence-scored event loaded from JSON uses the
  tracked delete path. Manual edits invalidate pending rows.
- Single-row review selects the following row after refresh, or the preceding row
  when the reviewed row was last; ordinary selection signaling seeks playback.
- Main-window shortcuts invoke the panel's selected-row intent surface. The
  controller remains unaware of key bindings and `QSettings` shortcut values.
- Table confidence-cell confirmation prompt supports `Yes` (confirm), `No` (reject), `Cancel` (no-op).
- Rejecting an inferred row removes it from the review table.
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
  localization table edits rely on old/new event matching. A valid normalized
  `timestamp_utc` is the stable temporal key; use `position_ms` only for legacy
  or malformed annotations, alongside `head` and `label`.
- Projection contract:
  table rows and markers consume projected copies. Selection and playback must
  not mutate canonical annotation JSON.
- Dialog flows:
  keep pause/resume signal toggling symmetric (toggle before + after) when modal input is used.
- Schema edits and event edits are coupled:
  head/label renames must keep existing events coherent.
- Smart tab and hand tab behavior differs; when changing tab logic, verify marker behavior in both.
- Always keep no-op checks for unchanged event modifications.
