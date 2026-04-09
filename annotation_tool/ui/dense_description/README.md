# Dense Description UI

## Role
Provides the Dense Description right-panel with table and add-event adapters.

## Architecture Context
- Static layout comes from `dense_annotation_panel.ui`.
- `DenseAnnotationPanel` builds runtime adapters and table model in `__init__.py`.
- Business logic is handled by `DenseEditorController`.

## Public Surface
### Main Class
- `DenseAnnotationPanel`

### Supporting Classes
- `DenseTableModel`
- `_DenseTableAdapter`
- `_DenseInputAdapter`

### Panel Signal
- `eventNavigateRequested(int)`

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
- `_apply_dense_column_ratio()`
  - Maintains Time/Lang/Description column width ratio.
- `DenseTableModel.setData(...)`
  - Emits old/new row payload on effective edits.
- `_DenseTableAdapter.set_data(...)`
  - Replaces displayed annotations.

## Business Rules
- Table emits edit intents; controller validates and persists changes.
- Add-event button only emits intent.
- Column widths are kept stable across resize events.

## Conventions
- Keep widget layout in `.ui` and adapter behavior in Python.
- Preserve table adapter API used by controller/tests.

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
