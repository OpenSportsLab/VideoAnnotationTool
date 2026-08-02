# Dataset Explorer Panel UI

## Role
Provides the left dock dataset explorer tree, header inspector tables, and explorer-level UI actions.

## Architecture Context
- `DatasetExplorerPanel` is the view surface used by `DatasetExplorerController`.
- `DatasetExplorerTreeModel` is a data-backed `QAbstractItemModel` that projects
  runtime sample entries without allocating one Qt item per row.
- Header tables support known/unknown project fields and raw JSON preview text.

## Public Surface
### Main Classes
- `DatasetExplorerTreeModel`
- `DatasetExplorerPanel`

### Model Roles
- `FilePathRole`
- `DataIdRole`
- `SortRole`
- `InputTypeRole`
- `BallPathRole`

### Panel Signals
- `removeItemRequested(QModelIndex)`
- `addDataRequested()`
- `sampleNavigateRequested(int)`
- `headerDraftChanged(dict)`

## Key Functions and Responsibilities
- `DatasetExplorerTreeModel.set_entries(...)`
  - Resets the filtered/sorted projection, exposes the first 500 samples, and
    schedules later batches on zero-delay event-loop turns.
- `index_for_sample_id(...)`, `index_for_path(...)`, `ensure_sample_exposed(...)`
  - Provide constant-time controller lookup without a `QStandardItem` map.
- `refresh_sample(...)`
  - Emits a lightweight row update for status/display changes.
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
- Tree model is view data only. Inline `setData()` emits a rename intent;
  canonical JSON mutation remains in history/controller layers.
- Each reset increments a generation token. Pending exposure callbacks from a
  prior dataset, filter, sort, or structural refresh must exit without changes.
- Filtering builds a new projection rather than hiding thousands of view rows.
- Selecting another input child in the active sample is focus-only: the
  controller highlights its viewer without rerouting media, refreshing
  annotation panels, or changing time.
- Selecting a parent sample clears input focus and preserves playback state;
  parent selection never forces autoplay.

## Conventions
- Keep roles and signal names stable for controller use.
- Keep heavy dataset logic out of this UI module.

## Interactions
- Inbound from controller:
  - runtime entries, filter projection, lightweight row refresh, and lazy raw
    JSON refresh.
- Outbound to controller:
  - add/remove/navigation/header-draft intents.

## Tests
- `tests/gui/test_dataset_explorer_focused.py`
- `tests/gui/test_dataset_explorer_regressions.py`
- `tests/gui/test_core_lifecycle.py`

## Developer Knowledge
- Role values (`FilePathRole`, `DataIdRole`) are used pervasively by controllers/tests; treat them as stable API.
- All Qt model resets/inserts remain on the GUI thread. Only exposure is
  chunked; canonical dataset preparation is complete before the first batch.
- Header editor emits staged draft updates; do not write directly to dataset from this module.
- Context-menu remove behavior expects selected index fidelity (parent vs child row); keep this distinction intact.
