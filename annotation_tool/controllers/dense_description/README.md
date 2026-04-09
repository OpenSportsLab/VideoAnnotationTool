# Dense Description Controller

## Role
Owns Dense Description mode behavior for timestamped text event CRUD and marker/table synchronization.

## Architecture Context
- `DenseEditorController` is selection-driven.
- Emits add/modify/delete intents to `HistoryManager`.
- Uses center panel playback position for timing and navigation.

## Public Surface
### Class
- `DenseEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
- `denseEventAddRequested(str, dict)`
- `denseEventModRequested(str, dict, dict)`
- `denseEventDelRequested(str, dict, int)`

## Key Functions and Responsibilities
- `setup_connections()`
  - Binds add button, table CRUD, and event navigation.
- `on_mode_changed(index)`
  - Refreshes dense display when mode becomes active.
- `on_data_selected(data_id)`
  - Loads dense events for selected sample.
- `_on_add_event_requested(initial_text="")`
  - Modal add flow; creates event at current time and emits add intent.
- `_on_annotation_modified(old_event, new_event)`
  - Emits modification intent with no-op guard.
- `_on_delete_single_annotation(item_data)`
  - Emits delete intent for selected event.
- `display_events_for_item(path, update_markers=None)`
  - Renders sorted events table and timeline markers.

## Business Rules
- Add flow requires non-empty text.
- Edit/delete require valid selected sample/event.
- No-op modifications are ignored.
- Marker refresh is mode-aware.

## Conventions
- Keep business mutation policy out of UI adapters.
- Use signal-based mutation requests only.

## Interactions
- Inbound:
  - `DatasetExplorerController.dataSelected -> on_data_selected`
  - `MediaController.playbackStateChanged -> on_playback_state_changed`
- Outbound:
  - Dense mutation signals -> `HistoryManager.execute_dense_event_*`

## Tests
- `tests/gui/test_workflow_dense_description.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Add flow contract:
  Add action creates exactly one new event mutation (or no-op on cancel/empty text).
- Table-edit contract:
  dense event edits should be table-driven and emit old/new payload with no-op guard.
- Modal pause/resume:
  preserve symmetric play/pause toggles around modal input when media was already playing.
- Marker contract:
  marker refresh should remain mode-aware and tied to current selected sample path.
