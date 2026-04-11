# Dataset Explorer Panel UI

## Role
Provides the left dock dataset explorer tree, header inspector tables, and explorer-level UI actions.

## Architecture Context
- `DatasetExplorerPanel` is the view surface used by `DatasetExplorerController`.
- `DatasetExplorerTreeModel` stores row metadata (file paths + sample IDs).
- Header tables support known/unknown project fields and raw JSON preview text.

## Public Surface
### Main Classes
- `DatasetExplorerTreeModel`
- `DatasetExplorerPanel`

### Model Roles
- `FilePathRole`
- `DataIdRole`

### Panel Signals
- `removeItemRequested(QModelIndex)`
- `addDataRequested()`
- `sampleNavigateRequested(int)`
- `headerDraftChanged(dict)`

## Key Functions and Responsibilities
- `DatasetExplorerTreeModel.add_entry(...)`
  - Adds top-level sample row and optional child source rows.
- `DatasetExplorerPanel._set_context_menu_enabled(...)`
  - Enables remove context menu actions.
- `set_header_rows(known, unknown, draft, key_order=None)`
  - Populates header inspector tables from controller data.
- `_on_known_header_item_changed(...)`
  - Emits staged header draft updates.
- `set_raw_json_text(raw_json)`
  - Updates read-only JSON preview widget.

## Business Rules
- Header draft updates are staged via signal; controller decides persistence.
- Tree model is view data only; dataset mutation logic is external.

## Conventions
- Keep roles and signal names stable for controller use.
- Keep heavy dataset logic out of this UI module.

## Interactions
- Inbound from controller:
  - tree population, filter-driven row visibility, header/raw JSON refresh.
- Outbound to controller:
  - add/remove/navigation/header-draft intents.

## Tests
- `tests/gui/test_dataset_explorer_focused.py`
- `tests/gui/test_dataset_explorer_regressions.py`
- `tests/gui/test_core_lifecycle.py`

## Developer Knowledge
- Role values (`FilePathRole`, `DataIdRole`) are used pervasively by controllers/tests; treat them as stable API.
- Header editor emits staged draft updates; do not write directly to dataset from this module.
- Context-menu remove behavior expects selected index fidelity (parent vs child row); keep this distinction intact.
