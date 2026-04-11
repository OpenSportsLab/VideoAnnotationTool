# Classification Controllers

## Role
Implements Classification mode behavior and coordinates smart inference/train helpers.

## Architecture Context
- `ClassificationEditorController` manages panel behavior for Classification mode.
- Constructor takes only the classification panel object.
- Controller does not own dataset model state (`self.model` is not used).
- Runtime context is supplied via signal-slot wiring in `MainWindow.connect_signals()`:
  - sample selection snapshots
  - schema snapshots
- Dataset model ownership for smart inference/training lives in helper services wired from `MainWindow` through `set_dataset_model(...)`.

## Public Surface
### Class
- `ClassificationEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
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
- `on_selected_sample_changed(sample, resolved_path="")`
  - Refreshes manual/smart display for selected sample snapshot.
- `on_schema_context_changed(schema)`
  - Rebuilds dynamic schema-driven controls from runtime schema context.
- `save_manual_annotation(override_data=None, show_feedback=True)`
  - Normalizes annotation payload and emits tracked save intent.
- `confirm_smart_annotation_as_manual()`
  - Delegates smart confirmation flow to `InferenceManager`.
- `clear_current_manual_annotation()` / `clear_current_smart_annotation()`
  - Clears manual/smart state with proper history behavior.

## Business Rules
- Manual tab changes save immediately when effective value differs.
- No-op saves (same normalized annotation) do nothing.
- Schema operations enforce duplicate checks.

## Conventions
- UI stays in panel classes; controller performs behavior orchestration.
- Mutation commits are signal-based to `HistoryManager`.
- Keep constructor boundary clean: panel-only constructor.

## Interactions
- Inbound:
  - `DatasetExplorerController.sampleSelectionChanged -> on_selected_sample_changed`
  - `DatasetExplorerController.schemaContextChanged -> on_schema_context_changed`
  - `main_window` mode change fanout -> `on_mode_changed`
- Outbound:
  - Mutation signals -> `HistoryManager.execute_*`
  - Status/save/item refresh signals -> shell wiring in `main_window`

## Tests
- `tests/gui/test_workflow_classification.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Manual save path:
  normalize selection payload before emitting `manualAnnotationSaveRequested`.
- No-op guard:
  unchanged manual annotation must not emit mutation intent.
- Dynamic schema UI:
  always reconnect dynamic group signals after rebuilding groups (`setup_dynamic_ui` + `_connect_dynamic_type_buttons`).
