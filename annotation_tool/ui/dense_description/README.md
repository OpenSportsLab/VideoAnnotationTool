# Dense Description UI

## Role
Provides the Dense Description right-panel with table and add-event adapters.

Includes the shared bottom inference-review footer and pending-row review.

## Architecture Context
- Static layout comes from `dense_annotation_panel.ui`.
- `DenseAnnotationPanel` builds runtime adapters and table model in `__init__.py`.
- Business logic is handled by `DenseEditorController`.
- Panel exposes a stable controller-facing API and signal surface.

## Public Surface
### Main Class
- `DenseAnnotationPanel`

### Supporting Classes
- `DenseTableModel`
- `_DenseTableAdapter`
- `_DenseInputAdapter`

### Panel Signal
- `eventNavigateRequested(int)`
- `addEventRequested()`
- `eventSelected(int)`
- `eventDeleted(dict)`
- `eventModified(dict, dict)`
- `updateTimeForSelectedRequested(dict)`
- `smartConfirmRequested()` / `smartRejectRequested()`
- `smartAcceptAllRequested()` / `smartRejectAllRequested()`

### Table Adapter Signals
- `annotationSelected(int)`
- `annotationModified(dict, dict)`
- `annotationDeleted(dict)`
- `updateTimeForSelectedRequested(dict)`

### Input Adapter Signal
- `addEventRequested()`

## Key Functions and Responsibilities
- `DenseAnnotationPanel.__init__()`
  - Loads `.ui`, initializes adapters/model, configures editing behavior.
- `set_events(annotations)`
  - Replaces displayed dense events.
- `set_timeline_origin(origin_utc)`
  - Enables full UTC display/editing for resolvable rows while preserving relative fallback.
- `set_dense_enabled(enabled)`
  - Applies panel enabled/disabled state.
- `get_selected_event()`, `select_row_by_time(...)`, `select_event(...)`
  - Controller-facing selection helpers without exposing table internals.
- `_apply_dense_column_ratio()`
  - Maintains Time/Lang/Description column width ratio.
- `DenseTableModel.setData(...)`
  - Emits old/new row payload on effective edits.

## Business Rules
- Table emits edit intents; controller validates and persists changes.
- Add-event button only emits intent.
- `InferenceReviewBar` is always the final layout widget and contains review
  actions only; execution starts from the Inference Jobs dock.
- The Time column reserves enough width for full UTC timestamps across resize events.
- UTC Time edits normalize ISO-compatible input and emit both temporal fields;
  invalid input is a no-op. Relative rows retain the relative-time parser.
- `select_row_by_time(...)` and `select_event(...)` are programmatic
  highlight-only helpers. They block selection signals so refreshes and tab
  switches cannot seek to a previously selected annotation.

## Conventions
- Keep widget layout in `.ui` and adapter behavior in Python.
- Preserve compatibility fields (`table`, `input_widget`) used by tests.

## Interactions
- Inbound from controller:
  - set table data, selection updates, panel enable state.
- Outbound to controller:
  - add/edit/delete/time-update intent signals.

## Tests
- `tests/gui/test_workflow_dense_description.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Keep table column order contract (`Time`, `Lang`, `Description`) stable unless controller/tests are updated.
- `_apply_dense_column_ratio()` affects edit usability; validate on narrow and wide layouts after UI changes.
- Add button emits intent only; avoid persisting state inside UI layer.
