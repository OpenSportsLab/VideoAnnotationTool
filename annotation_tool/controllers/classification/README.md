# Classification Controllers

## Role
Implements Classification mode logic and coordinates smart inference/train helpers.

## Architecture Context
- `ClassificationEditorController` manages panel behavior for Classification mode.
- It receives selection context from `DatasetExplorerController` and emits mutation intents to `HistoryManager`.
- It delegates smart inference/training operations to helper services.

## Public Surface
### Class
- `ClassificationEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
- `filterRefreshRequested(int, str)`
- `manualAnnotationSaveRequested(str, object, bool)`
- `schemaHeadAddRequested(str, dict)`
- `schemaHeadRemoveRequested(str)`
- `schemaLabelAddRequested(str, str)`
- `schemaLabelRemoveRequested(str, str)`

### Helpers
- `InferenceManager`
- `TrainManager`

## Key Functions and Responsibilities
- `setup_connections()`
  - Connects classification panel UI actions to controller actions.
- `on_mode_changed(index)`
  - Tracks active mode and updates marker display state.
- `on_data_selected(data_id)`
  - Refreshes manual/smart display for selected sample.
- `save_manual_annotation(override_data=None, show_feedback=True)`
  - Normalizes annotation payload and emits tracked save intent.
- `confirm_smart_annotation_as_manual()`
  - Confirms smart predictions (single or batch) and updates tracked state.
- `clear_current_manual_annotation()` / `clear_current_smart_annotation()`
  - Clears annotation state with proper history behavior.
- `handle_add_label_head(name)` / `handle_remove_label_head(head)`
  - Schema head CRUD flow.
- `add_custom_type(head)` / `remove_custom_type(head, label)`
  - Schema label CRUD flow.

## Business Rules
- Manual tab changes save immediately when effective value differs.
- No-op saves (same normalized annotation) do nothing.
- Schema operations enforce duplicate checks.
- Filter refresh is emitted after relevant mutation flows.

## Conventions
- UI stays in panel classes; controller performs behavior orchestration.
- Mutation commits are signal-based to `HistoryManager`.
- Avoid direct dataset lifecycle logic in this module.

## Interactions
- Inbound:
  - `DatasetExplorerController.dataSelected -> on_data_selected`
  - `main_window` mode change fanout -> `on_mode_changed`
- Outbound:
  - Mutation signals -> `HistoryManager.execute_*`
  - Status/save/item refresh signals -> shell wiring in `main_window`

## Tests
- `tests/gui/test_workflow_classification.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- `on_data_selected()` assumes `data_id -> path` resolution from dataset explorer; keep this contract stable.
- Manual save path:
  normalize selection payload before emitting `manualAnnotationSaveRequested`.
- No-op guard:
  unchanged manual annotation must not emit mutation intent.
- Smart confirm/clear currently updates smart state inside controller for existing flows; if you centralize further, keep stack behavior identical.
- Dynamic schema UI:
  always reconnect dynamic group signals after rebuilding groups (`setup_dynamic_ui` + `_connect_dynamic_type_buttons`).
