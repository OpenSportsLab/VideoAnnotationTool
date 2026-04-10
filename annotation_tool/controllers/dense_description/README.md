# Dense Description Controller

## Role
Owns Dense Description mode behavior for timestamped text event CRUD and marker/table synchronization.

## Architecture Context
- `DenseEditorController` is selection-driven and consumes selected sample payloads.
- Constructor takes only the dense panel object.
- It consumes panel-level signals/methods and receives resolved sample path context through `MainWindow.connect_signals()` wiring.
- Runtime playback state and media position are refreshed via signal-slot wiring from `MainWindow.connect_signals()`.
- Emits add/modify/delete intents to `HistoryManager`.
- Requests media operations and marker updates through outbound signals.

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
- `mediaSeekRequested(int)`
- `markersUpdateRequested(object)`

## Key Functions and Responsibilities
- `setup_connections()`
  - Binds panel-level add/edit/delete/select/time-update and navigation intents.
- `on_mode_changed(index)`
  - Refreshes dense display when mode becomes active.
- `on_selected_sample_changed(sample)`
  - Loads selected sample snapshot and refreshes dense events.
- `_on_add_event_requested(initial_text="")`
  - Modal add flow; creates event at current time and emits add intent.
- `_on_annotation_modified(old_event, new_event)`
  - Emits modification intent with no-op guard.
- `_on_delete_single_annotation(item_data)`
  - Emits delete intent for selected event.
- `display_events_for_item(path, update_markers=None)`
  - Refreshes currently selected dense display state.

## Business Rules
- Add flow requires non-empty text.
- Edit/delete require valid selected sample/event.
- No-op modifications are ignored.
- Marker refresh is mode-aware.

## Conventions
- Keep business mutation policy out of UI adapters.
- Use signal-based mutation requests only.
- Keep controller-panel boundary clean: use `DenseAnnotationPanel` API (`set_events`, `get_selected_event`, `select_event`, `set_dense_enabled`).

## Interactions
- Inbound:
  - `DatasetExplorerController.sampleSelectionChanged -> on_selected_sample_changed`
  - `MediaCenterPanel.positionChanged -> on_media_position_changed`
- Outbound:
  - Dense mutation signals -> `HistoryManager.execute_dense_event_*`
  - Media/marker signals -> `MainWindow.connect_signals()` routing

## Tests
- `tests/gui/test_workflow_dense_description.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Add flow contract:
  Add action creates exactly one new event mutation (or no-op on cancel/empty text).
- Table-edit contract:
  dense event edits should be table-driven and emit old/new payload with no-op guard.
- Modal add behavior:
  Add click is wired in `MainWindow.connect_signals()` to `MediaController.pause`; dense controller does not track playback state and does not auto-resume.
- Marker contract:
  marker refresh should remain mode-aware and tied to current selected sample path.
