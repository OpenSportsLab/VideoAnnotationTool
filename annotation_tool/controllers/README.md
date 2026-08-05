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
- `hf_transfer_controller.py`: threaded Hugging Face dataset transfer and local-model cache orchestration for GUI actions.
- `inference_controller.py`: canonical local/remote model discovery, execution,
  progress, cancellation, and worker lifecycle owner.
- `classification/`, `localization/`, `description/`, `dense_description/`, `question_answer/`: mode controllers.

## Key Functions and Responsibilities
### `DatasetExplorerController`
- `create_new_project_flow()`: create blank dataset (after close checks).
- `import_annotations()`, `open_project_from_path()`, `load_project()`: open/normalize/load dataset.
- `save_project()`, `export_project()`: write dataset JSON to disk.
- `populate_tree()`, `handle_filter_change()`: build the runtime projection and
  establish its bounded page.
- `_on_selection_changed()`, `_route_media_for_selection()`, `_focus_media_for_selection()`: selection context plus preserve-state route, ordinary route, or focus-only media intent emission.
- `handle_add_sample()`, `handle_remove_item()`, `handle_clear_workspace()`: explorer mutation intent emission (`handle_add_sample()` accepts files/folders in one picker; files map to single-input samples, folders expand recursively to multi-input samples).
- `restore_dataset_json_from_history()`: apply history snapshot restore.

### `HistoryManager`
- `perform_undo()`, `perform_redo()`: history transitions.
- `execute_*` methods: forward mutation entrypoints for classification/localization/description/dense/explorer edits.
- `_apply_state_change()`: command-type-specific replay for undo/redo.

### `MediaController`
- `route_media_group(sources, focused_path, ensure_playback)`: canonical sample-level route. One session is created per input; focusing an existing pane does not reload the group.
- `focus_source(path)`: changes only the focused pane highlight and preserves
  group position and playback state.
- `toggle_play_pause()`, `stop()`, `seek_relative()`, `set_position()`, `set_playback_rate()`: shared-clock playback control.
- `playback_rate()` returns the authoritative active rate. Every single,
  grouped, and synchronization playback route updates it so a settings change
  can preserve a represented rate or reset a removed rate to `1x`.
- `go_to_source_start(path)`, `go_to_source_end(path)`: seek the shared clock to a modality boundary. Timestamped backends use their first/last frame times; video end uses media duration.
- `enter_sync_mode(path)`, `step_sync_frame(direction)`, `apply_sync_mode()`, `cancel_sync_mode()`: selected-session visual UTC synchronization lifecycle.
- `is_muted()`, `set_muted()`, `toggle_mute()`: mute control and signaling.
- `timelineOriginChanged(sample_id, origin_utc)`: publishes sample-scoped temporal projection context.
- `inputUtcStartMutationRequested(path, utc_text)`: requests one atomic dataset/history update after Apply.
- `inputUtcStartRemovalRequested(path)`: requests removal of an explicit input UTC override.
- Internal structure:
  `MediaController` owns the group clock and session records; format-specific playback lives under `media/`, with shared raster runtime in `media/raster_backend.py`.

### UTC Synchronization Contract

- Each valid session record may expose `origin_utc`. A valid input-level
  `UTC_time_start` overrides a backend-derived origin. An invalid explicit value
  forces relative alignment.
- The sample origin is the earliest valid session origin; duration is the union
  through the latest session end. Relative inputs have offset zero.
- A running video may be the native group clock. Periodic drift correction must
  not seek that clock, but every explicit group seek must reposition it before
  the next clock tick; otherwise the old player position overwrites the seek.
- Sync entry freezes the group at `anchor_utc = group_origin + group_position`
  and redirects playback commands to the selected session's local timeline.
- Apply computes `UTC_time_start = anchor_utc - selected_local_position` and
  serializes six fractional digits.
- `MainWindow.connect_signals()` routes the mutation request to
  `HistoryManager.execute_input_utc_start_update(...)`. The explorer updates
  `UTC_time_start` while authoritative annotation `timestamp_utc` values remain
  unchanged; one JSON snapshot command makes the operation undoable. A
  semantically equivalent UTC value is a no-op.
- UTC-start update/removal receives the pre-change timeline origin, promotes
  resolvable legacy annotations first, and then normalizes compatibility
  positions against the new origin. There is no annotation-shift payload on the
  media signal or history API.
- After mutation, the sample is rerouted and sought back to the same absolute
  anchor, paused. Project/sample changes cancel an active synchronization
  without mutation.
- Viewer context actions can set/correct the UTC value at modality local zero or
  remove the explicit override. These use the same one-command history path;
  removal restores backend-derived UTC when the modality provides it.

### `WelcomeController`
- `_setup_connections()`: welcome signal wiring to dataset routes.
- `_open_recent_project()`, `_remove_recent_project()`, `refresh_recent_projects()`: recent-project UX.

### `HfTransferController`
- `start_download(...)`: execute Hugging Face dataset download in a worker thread.
- `start_upload(...)`: execute Hugging Face dataset upload from local dataset JSON inputs in a worker thread.
- `start_model_import(...)`: inspect and cache one OpenSportsLib model repository
  through `_HfModelWorker`. Its started/progress/completed/failed/cancelled
  signals are routed by `MainWindow` to the active Settings draft; Settings
  widgets never hold the controller. `shutdown()` interrupts and waits for all
  dataset and model workers.
- Emits start/progress/completion/failure signals for UI wiring in `main_window.py`.

### `InferenceController`
- Owns independent Local and Remote FIFO queues. Each lane has at most one
  worker, the two lanes may overlap, and providers are instantiated only when
  their requests reach the front.
- Aggregates runnable task models into provider-aware choices. Local discovery
  always runs; Remote discovery runs only when explicitly enabled and failures
  are non-fatal when Local choices remain available. Identical model IDs remain
  distinct through their `(backend, model_id)` identity.
- Application Settings is the sole setup surface. Run requests contain an
  immutable snapshot of saved Local registry, Remote endpoint, enablement, and
  shared mappings; the run dialog only chooses a model and runtime parameters.
- The last successfully completed `(backend, model_id)` is stored per task and
  used as the preferred choice on the next run when still available.
- `enqueue_inference()`, `cancel_request()`, `cancel_all()`, `queue_snapshot()`,
  `queueChanged`, and `clear_queue_history()` form the queue interface.
  Immutable `InferenceQueueEntry` snapshots drive the Inference Jobs dock. Each
  entry includes a bounded immutable event timeline; repeated stage progress is
  coalesced and the latest 20 terminal entries remain session-only.
- Provider work runs in one `QThread` per active lane; `MainWindow` leaves
  navigation, editing, and further inference submission enabled. A generic
  post-provider cancellation check suppresses late Local results.
- `controllers.inference_runtime.configure_compute_device` is the canonical
  direct-library device resolver for Classification and Localization. It
  preserves explicit CPU and converts unavailable `auto`/CUDA requests to CPU
  in temporary per-job configs, including legacy and canonical GPU fields.
- The Local VQA adapter builds a temporary config before constructing
  `VQAModel`: system output paths become job-local, device/dtype are made
  CPU-safe, adjacent X-VARS dependencies are resolved, and stale missing
  publisher paths fail with `local_model_dependency_missing`. OpenSportsLib
  0.3 `data[].answer_text` output is normalized at the provider boundary.
- Result validation correlates by request `item_id`, then unique request
  `sample_id`, with positional fallback restricted to legacy Local OSL output.
- `MainWindow` preserves the user's active annotation and head tabs while
  dispatching completed results. Classification batch input choices are shown
  from the selected sample and applied positionally to each queued sample.
- `MainWindow` also owns the Inference Jobs dock visibility preference. Welcome
  mode hides the dock without overwriting that preference and disables its View
  action; workspace mode restores it alongside the other project docks.
  Canonical request IDs overwrite result-owned IDs; unknown and duplicate
  targets are invalid results.
- `DatasetExplorerController.project_generation` increments on every reset.
  Main-window request state captures that generation and the complete
  item-to-sample mapping, cancels both active jobs and all waiting jobs on
  generation change, discards missing sample targets, and never routes
  predictions through the current selection.
- The local registry is authoritative and may be empty; local discovery never
  injects built-in model descriptors. The three curated OpenSportsLab IDs live
  only in `KNOWN_HF_LOCAL_MODEL_IDS` as editable import-dialog suggestions. An
  explicit Hugging Face import pins cache paths and hidden
  repository/revision/checkpoint metadata in the draft registry.
  `RETIRED_LOCAL_MODEL_IDS` filters the two legacy `jeetv` defaults from older
  persisted settings during registry loading. `_is_obsolete_seeded_model()`
  also removes former OpenSportsLab seed rows while preserving explicit imports
  whose weights point into the Hugging Face cache.
- `hf_model_import.resolve_hf_local_model()` performs deterministic repository
  inspection, configuration/task validation, checkpoint selection, cache
  downloads, and cancellation checks. The request-scoped `force_download`
  option is forwarded to both `hf_hub_download` calls and is not persisted as
  model metadata. Only the two exact official
  localization repositories in `TRUSTED_LEGACY_HF_MODEL_IDS` may carry
  `trusted_legacy=True` through `ModelDescriptor` to `LocInferenceWorker`.
  Registry serialization revalidates that allowlist and revokes trust after a
  relevant manual edit.
- Local adapters call public OpenSportsLib task classes. Missing native
  Description/Dense APIs are advertised as unavailable rather than emulated.
- Remote execution resolves shared assets or resumable uploads, submits an
  idempotent job, polls terminal state, and validates task-native results.
- Mode controllers emit inference intent; `MainWindow.connect_signals()` adds
  canonical sample/schema context and routes results back. Mode controllers
  then emit ordinary mutation intents to `HistoryManager`.
- Upload manifests are application settings and never enter dataset JSON.

## Business Rules
- Dataset JSON mutation must preserve undo/redo correctness.
- No-op mutation requests should not change stacks.
- Save/export normalizes temporal annotations using a genuine resolved origin;
  it must not invent one for relative-only samples.
- Tab changes must not repopulate tree or restart media unnecessarily.
- Selecting an input child of the already active sample emits
  `mediaFocusRequested(path)`, not `mediaRouteRequested(...)`. `MainWindow`
  routes that intent to `MediaController.focus_source()` without touching the
  shared clock or playback state. The focus-only branch also does not re-emit
  `sampleSelectionChanged`; refreshing mode panels can re-emit a selected
  annotation and cause an unintended second seek.
- Explicit selection of a different sample/input emits
  `mediaSelectionRouteRequested(sources, focused_path)`. `MainWindow` snapshots
  `MediaController.is_playing()` before routing so the new group inherits the
  playing/paused state. A parent sample uses an empty `focused_path`; selecting
  the already active parent emits only `mediaFocusRequested("")`.
- Runtime sample/path indexes are constant-time. Status refreshes update model
  data by sample ID; they must not scan the complete dataset or recreate the
  tree unless confidence sorting changes row order.
- Large trees expose one bounded page (500 samples by default, configured through
  application settings). Boundary wheel actions replace
  that page instead of accumulating rows. The controller guards page resets so
  an off-page active sample retains annotation and playback state; returning to
  its page restores the tree highlight without routing media again.
- Boundary scrolling uses relative `pageNavigateRequested` intents and retains
  direction-specific scroll placement. The bottom controls use zero-based
  absolute `pageRequested` intents and position direct destinations at the top.
- Raw JSON preview serialization is dirty-tracked and runs only while the JSON
  inspector tab is active. Editor action-list signals contain only sample ID,
  name, and path; batch range widgets populate from that cache on first use.
- A valid temporal-annotation `timestamp_utc` is authoritative. Controllers use
  projected `position_ms` values for UI/playback, while UTC alignment edits
  preserve absolute instants and recompute only compatibility positions.

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
- Shared temporal policy lives in `annotation_tool/utils.py`: parse/normalize
  UTC, resolve a genuine sample origin, project annotations, normalize them for
  writes, and choose timestamp-first annotation identities. Do not duplicate
  these rules in mode controllers.
- Pane context menus emit intents only. Keep group boundary seeking and sync
  eligibility in `MediaController`.
- Undo/redo correctness is a business contract, not optional behavior.
- Avoid duplicating mutation logic across explorer/mode controllers/history; use one canonical implementation.
