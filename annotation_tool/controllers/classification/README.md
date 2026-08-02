# Classification Controllers

## Role
Implements Classification mode behavior and coordinates transient inference review and training.

The bottom **Run Inference…** footer emits shared inference intent through
`MainWindow`; current-sample and batch scope are selected in the shared dialog.

## Architecture Context
- `ClassificationEditorController` manages panel behavior for Classification mode.
- Constructor takes only the classification panel object.
- Controller does not own dataset model state (`self.model` is not used).
- Runtime context is supplied via signal-slot wiring in `MainWindow.connect_signals()`:
  - sample selection snapshots
  - schema snapshots
- The central `InferenceController` owns Local/Remote execution; this controller
  only normalizes results into transient per-sample candidates.

## Public Surface
### Class
- `ClassificationEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
- `manualAnnotationSaveRequested(str, object, bool)`
- `schemaHeadAddRequested(str, dict)`
- `schemaHeadRenameRequested(str, str)`
- `schemaHeadRemoveRequested(str)`
- `schemaLabelAddRequested(str, str)`
- `schemaLabelRemoveRequested(str, str)`

### Helper
- `TrainManager`

## Key Functions and Responsibilities
- `setup_connections()`
  - Connects classification panel UI actions, including head-tab add/rename/delete intents, to controller actions.
- `on_selected_sample_changed(sample)`
  - Refreshes manual/smart display for selected sample snapshot.
- `on_schema_context_changed(schema)`
  - Rebuilds dynamic schema-driven controls from runtime schema context.
- `save_manual_annotation(override_data=None, show_feedback=True)`
  - Normalizes annotation payload and emits tracked save intent.
- `confirm_smart_annotation_head(head)` / `reject_smart_annotation_head(head)`
  - Accept or discard one transient inferred label.
- `clear_current_manual_annotation()` / `clear_current_smart_annotation()`
  - Clears manual/smart state with proper history behavior.

## Business Rules
- Manual tab changes save immediately when effective value differs.
- No-op saves (same normalized annotation) do nothing.
- Schema operations enforce duplicate checks and route through `HistoryManager`.
- Head/category management is tab-driven; create still prompts for `single_label` vs `multi_label`.
- Predictions remain in a per-sample transient review store.
- Accepting writes the plain `labels[head]` value through `HistoryManager`;
  rejecting never mutates the dataset.
- The annotation panel exposes only the shared bottom inference footer; there
  are no per-head or separate batch execution buttons.

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
