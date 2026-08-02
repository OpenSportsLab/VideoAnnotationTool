# Classification UI

## Role
Provides the Classification right-panel widgets and dynamic label-group controls.

Includes the shared bottom prediction-review footer used by every annotation panel.

## Architecture Context
- Static layout comes from `classification_annotation_panel.ui`.
- Runtime dynamic controls and signal plumbing are implemented in `__init__.py`.
- Business logic is handled by `ClassificationEditorController`.

## Public Surface
### Main Class
- `ClassificationAnnotationPanel`

### Supporting Classes
- `NativeDonutChart`
- `DynamicSingleLabelGroup`
- `DynamicMultiLabelGroup`

### Panel Signals
- `head_add_requested(str)`
- `head_rename_requested(str, str)`
- `head_delete_requested(str)`
- `head_selected(str)`
- `head_smart_confirm_requested(str)`
- `head_smart_reject_requested(str)`
- `annotation_saved(dict)`
- `hand_clear_requested()`
- `acceptAllPredictionsRequested()`
- `rejectAllPredictionsRequested()`

## Key Functions and Responsibilities
- `setup_dynamic_labels(label_definitions)`
  - Rebuilds the schema-driven head tabs and their per-head label controls.
- `set_annotation(data)` / `get_annotation()`
  - Controller-facing read/write surface for manual annotations.
- `clear_selection()`
  - Clears all selected label values.
- `set_current_head(head_name)` / `get_current_head()`
  - Keeps the selected category tab stable across schema refreshes when possible.
- `display_inference_result(...)`
  - Updates per-row pending controls (confidence + accept/reject) for inferred labels.
- `reset_smart_inference()` / `reset_train_ui()`
  - Resets smart/train related UI state.

## Business Rules
- Dynamic controls are schema-driven at runtime.
- Category management is tab-driven; the old category editor is hidden.
- A trailing `+` tab creates a new category, and tab context actions own rename/delete.
- UI emits intent signals only; it does not commit dataset mutations.
- Pending state is rendered at row level inside each head group.
- There are no per-head, single, or batch inference buttons; scope is selected
  in the shared run dialog.
- `InferenceReviewBar` is the last widget and contains review actions only;
  execution starts from the main-window Inference Jobs dock.
- The training tab is intentionally hidden for now; keep the train widgets/API stable behind the panel until the training flow is repaired.

## Conventions
- Keep `.ui` static and reusable.
- Keep dynamic widget creation in Python (`__init__.py`).
- Preserve stable API names consumed by controllers/tests.

## Interactions
- Inbound from controller:
  - setup dynamic labels, set/get annotation, pending output display.
- Outbound to controller:
  - user actions via panel signals listed above.

## Tests
- `tests/gui/test_workflow_classification.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Dynamic label groups are frequently rebuilt; always reconnect callbacks after rebuilding.
- Keep signal payload types stable (`dict`, `(int, int)`, etc.) because controller logic expects exact shapes.
- Donut chart is presentation-only; do not embed inference decision logic in UI class methods.
