# Controllers Module

## Role
Owns runtime business logic: dataset lifecycle, mutation history, playback control, welcome routing, and mode-specific editor behavior.

## Architecture Context
- `DatasetExplorerController` is the canonical dataset owner.
- Mode controllers manage per-mode UI behavior and emit mutation intents.
- `HistoryManager` executes tracked mutations and undo/redo state transitions.
- `MediaController` centralizes playback state and routing logic.
- `main_window.py` connects all cross-controller signals.

## Public Surface
- `command_types.py`: `CmdType` enum for undo/redo command types.
- `dataset_explorer_controller.py`: dataset and explorer orchestration.
- `history_manager.py`: mutation/undo/redo engine.
- `media_controller.py`: grouped media playback, UTC alignment, synchronization, and mute routing.
- `media/`: internal playback backends used by `MediaController` (`video`, `frames_npy`, `tracking_parquet`).
- `welcome_controller.py`: welcome-page routing.
- `hf_transfer_controller.py`: threaded Hugging Face download/upload orchestration for GUI menu actions.
- `classification/`, `localization/`, `description/`, `dense_description/`, `question_answer/`: mode controllers.

## Key Functions and Responsibilities
### `DatasetExplorerController`
- `create_new_project_flow()`: create blank dataset (after close checks).
- `import_annotations()`, `open_project_from_path()`, `load_project()`: open/normalize/load dataset.
- `save_project()`, `export_project()`: write dataset JSON to disk.
- `populate_tree()`, `handle_filter_change()`: tree render + visibility filtering.
- `_on_selection_changed()`, `_route_media_for_selection()`: selection context and media route emission (resolved media source object, not just path).
- `handle_add_sample()`, `handle_remove_item()`, `handle_clear_workspace()`: explorer mutation intent emission (`handle_add_sample()` accepts files/folders in one picker; files map to single-input samples, folders expand recursively to multi-input samples).
- `restore_dataset_json_from_history()`: apply history snapshot restore.

### `HistoryManager`
- `perform_undo()`, `perform_redo()`: history transitions.
- `execute_*` methods: forward mutation entrypoints for classification/localization/description/dense/explorer edits.
- `_apply_state_change()`: command-type-specific replay for undo/redo.

### `MediaController`
- `route_media_group(sources, focused_path, ensure_playback)`: canonical sample-level route. One session is created per input; focusing an existing pane does not reload the group.
- `toggle_play_pause()`, `stop()`, `seek_relative()`, `set_position()`, `set_playback_rate()`: shared-clock playback control.
- `go_to_source_start(path)`, `go_to_source_end(path)`: seek the shared clock to a modality boundary. Timestamped backends use their first/last frame times; video end uses media duration.
- `enter_sync_mode(path)`, `step_sync_frame(direction)`, `apply_sync_mode()`, `cancel_sync_mode()`: selected-session visual UTC synchronization lifecycle.
- `is_muted()`, `set_muted()`, `toggle_mute()`: mute control and signaling.
- `inputUtcStartMutationRequested(path, utc_text, annotation_shift_ms)`: requests one atomic dataset/history update after Apply.
- Internal structure:
  `MediaController` owns the group clock and session records; format-specific playback lives under `media/`, with shared raster runtime in `media/raster_backend.py`.

### UTC Synchronization Contract

- Each valid session record may expose `origin_utc`. A valid input-level
  `UTC_time_start` overrides a backend-derived origin. An invalid explicit value
  forces relative alignment.
- The sample origin is the earliest valid session origin; duration is the union
  through the latest session end. Relative inputs have offset zero.
- Sync entry freezes the group at `anchor_utc = group_origin + group_position`
  and redirects playback commands to the selected session's local timeline.
- Apply computes `UTC_time_start = anchor_utc - selected_local_position` and
  serializes six fractional digits.
- If Apply changes the sample union origin, it also computes
  `annotation_shift_ms = old_union_origin - new_union_origin`.
- `MainWindow.connect_signals()` routes the mutation request to
  `HistoryManager.execute_input_utc_start_update(...)`. The explorer updates
  `UTC_time_start`, `events[].position_ms`, and
  `dense_captions[].position_ms`; one JSON snapshot command makes the entire
  operation undoable. A semantically equivalent UTC value is a no-op.
- After mutation, the sample is rerouted and sought back to the same absolute
  anchor, paused. Project/sample changes cancel an active synchronization
  without mutation.

### `WelcomeController`
- `_setup_connections()`: welcome signal wiring to dataset routes.
- `_open_recent_project()`, `_remove_recent_project()`, `refresh_recent_projects()`: recent-project UX.

### `HfTransferController`
- `start_download(...)`: execute Hugging Face dataset download in a worker thread.
- `start_upload(...)`: execute Hugging Face dataset upload from local dataset JSON inputs in a worker thread.
- Emits start/progress/completion/failure signals for UI wiring in `main_window.py`.

## Business Rules
- Dataset JSON mutation must preserve undo/redo correctness.
- No-op mutation requests should not change stacks.
- Tab changes must not repopulate tree or restart media unnecessarily.
- Timed annotations are relative to the shared union origin; UTC alignment edits
  must preserve their absolute UTC instants.

## Conventions
- Keep cross-controller coupling via signals.
- Keep mode-specific logic in mode controller modules.
- Keep dataset-level lifecycle in `DatasetExplorerController`.

## Tests
- `tests/gui/test_signal_decoupling_contract.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_dataset_explorer_focused.py`
- `tests/gui/test_dataset_explorer_regressions.py`

## Developer Knowledge
- Keep boundaries strict:
  dataset lifecycle in `DatasetExplorerController`, mutation/history in `HistoryManager`, playback in `MediaController`.
- Prefer signal contracts over direct controller reach-through.
- If adding a new mutation path:
  define request signal (if needed), implement `HistoryManager.execute_*`, add undo/redo handling and tests.
- Pane context menus emit intents only. Keep group boundary seeking and sync
  eligibility in `MediaController`.
- Undo/redo correctness is a business contract, not optional behavior.
- Avoid duplicating mutation logic across explorer/mode controllers/history; use one canonical implementation.
