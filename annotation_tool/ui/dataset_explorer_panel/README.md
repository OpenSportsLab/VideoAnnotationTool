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
- `pageNavigateRequested(int)`
- `pageRequested(int)`
- `headerDraftChanged(dict)`

## Key Functions and Responsibilities
- `DatasetExplorerTreeModel.set_entries(...)`
  - Resets the filtered/sorted projection and exposes its first bounded page.
- `set_page_size(...)`
  - Applies the validated application preference while retaining the current
    projection position; the default is 500 and the supported range is 100–2,000.
- `set_page(...)`, `next_page()`, `previous_page()`, `visible_range()`
  - Replace the visible slice without accumulating Qt rows.
- `index_for_sample_id(...)`, `index_for_path(...)`, `ensure_sample_visible(...)`
  - Provide constant-time lookup and open the containing page when requested.
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
- The tree exposes at most the configured page size. Scrolling beyond the bottom or
  top boundary requests the adjacent page; no page is loaded automatically.
- The pagination row directly beneath the tree emits a zero-based absolute `pageRequested` value
  from its one-based page field and buttons. Model notifications update the field
  under signal blocking so view synchronization never requests another page.
- Paging is a view-only reset. The controller suppresses the transient invalid
  Qt selection so off-page annotation and playback state remain active.
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
  - add/remove/sample navigation/relative or absolute page/header-draft intents.

## Tests
- `tests/gui/test_dataset_explorer_focused.py`
- `tests/gui/test_dataset_explorer_regressions.py`
- `tests/gui/test_core_lifecycle.py`

## Developer Knowledge
- Role values (`FilePathRole`, `DataIdRole`) are used pervasively by controllers/tests; treat them as stable API.
- All Qt model resets remain on the GUI thread. Canonical dataset preparation
  and the complete filtered/sorted projection exist independently of the page.
- Child input nodes are cached only for samples in the current page. Keep global
  ID/path indexes lightweight and never grow the Qt row set across page changes.
- Header editor emits staged draft updates; do not write directly to dataset from this module.
- Context-menu remove behavior expects selected index fidelity (parent vs child row); keep this distinction intact.
