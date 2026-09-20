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
  Both keep their synchronous success/failure return contract for the close
  flow, but run normalization and JSON writing in a
  `_DatasetSaveWorker` thread while a modal progress dialog processes GUI
  events. `_DatasetWriteSnapshot` contains only copied data and filesystem
  paths; the worker never accesses the controller or widgets. The worker writes
  a temporary file beside the destination. The GUI thread checks the project
  generation and snapshot before atomically replacing the destination and
  committing the normalized JSON. Failed or stale writes remove the temporary
  file and preserve the existing destination. No settings or JSON fields are
  added by this save path.
- `populate_tree()`, `handle_filter_change()`: build the runtime projection and
  establish its bounded page.
- `_on_selection_changed()`, `_route_media_for_selection()`, `_focus_media_for_selection()`: selection context plus preserve-state route, ordinary route, or focus-only media intent emission.
- `handle_add_sample()`, `handle_remove_item()`, `handle_clear_workspace()`: explorer mutation intent emission (`handle_add_sample()` accepts files/folders in one picker; files map to single-input samples, folders expand recursively to multi-input samples).
- `restore_dataset_json_from_history()`: apply history snapshot restore.
- `refresh_sample_rename_availability()`: owns the dataset-wide rename policy.
  For `hf_format == "parquet"` (case-insensitive), any missing input `path` or
  `ball_path`, resolved against the project root, locks all sample IDs. It sends
  the reason to the tree model for read-only flags, edit rejection, and tooltips,
  and returns that reason to callers. Runtime-index rebuilds refresh the policy;
  `MainWindow.connect_signals()` also wires download completion/failure/cancellation
  to refresh it without rebuilding the tree or restarting media. JSON/local
  datasets are unaffected. The policy requires no remote lookup or schema change.

### `HistoryManager`
- `perform_undo()`, `perform_redo()`: history transitions.
- `execute_*` methods: forward mutation entrypoints for classification/localization/description/dense/explorer edits.
- `_apply_state_change()`: command-type-specific replay for undo/redo.
- `execute_sample_id_rename()` rechecks rename availability before mutation,
  including delayed tree edits and direct requests. A blocked rename emits a
  status message and preserves JSON, dirty state, undo, and redo. Allowed edits
  retain the existing one-entry history contract; undo/redo restores snapshots.

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
- `set_media_availability_context(...)` receives Hugging Face provenance and
  absolute paths from the active selective request. Missing files for every
  supported input backend are classified before backend loading, and invalid
  panes are refreshed from “not downloaded” to “download in progress” without
  rebuilding the tree or changing selection.

### UTC Synchronization Contract

- Each valid session record may expose `origin_utc`. A valid input-level
  `UTC_time_start` overrides a backend-derived origin. An invalid explicit value
  forces relative alignment.
- The sample origin is the earliest valid session origin; duration is the union
  through the latest session end. Relative inputs have offset zero.
- Localization inference requests capture the offset between the earliest
  selected input origin and the whole-sample origin, plus an aligned per-input
  offset tuple. The local adapter chooses the offset from the inputs actually
  consumed by the model and adds it to input-relative predictions before
  results reach the mode controller. Thus an ignored selected video cannot
  suppress a later H5 offset. H5 origins use the cached earliest
  `timestamp_utc`, not row order.
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
  `queue_download(...)`, `pause_download_queue()`, and `resume_download_queue()`
  implement the controller-owned FIFO and preserve the active job at the front
  when stopped. The controller is the sole owner of ordered per-file entries,
  their queued/active/completed/failed state, byte totals, and average speed;
  `downloadQueueChanged` publishes read-only snapshots to the Transfers panel.
  `clear_queued_downloads()` removes completed and waiting entries without
  interrupting an active worker; a new sample auto-starts whenever that worker
  slot is idle.
  JSON-first media hydration is expanded into ordered per-input jobs here rather
  than delegated as one bulk library queue operation.
- `start_asset_download(...)`: selectively download one sample or input from an
  opened Hugging Face-sourced JSON. Additional selective requests join a FIFO
  queue behind the active selective worker. Cancelling for application shutdown
  clears the active worker and pending requests; the Transfers **Stop download**
  action instead pauses and requeues the active job. Runtime capability detection keeps full
  downloads usable with older OpenSportsLib releases.
  When the installed API accepts `byte_progress_cb`, `_HfDownloadWorker` emits
  `byteProgress(filename, downloaded_bytes, total_bytes)` for the Transfers
  dock; the callback is omitted for older runtime APIs. Optional OpenSportsLib
  lifecycle callbacks are adapted to file-plan, file-completed, and JSON-ready
  Qt signals. OpenSportsLib reports facts only; `HfTransferController` owns queue
  policy, row states, and completion aggregation, while `MainWindow` owns the
  cross-module open-JSON prompts.
  `MainWindow` handles selective failures while the FIFO continues through
  non-modal Transfers/status-bar messages. Terminal failure and cancellation for
  `assets` and `missing_assets` also use the dock without a message box, including
  the last queued input. Queue row failures remain owned by the controller;
  notification handling must not enter a modal event loop as worker completion
  can start the next queued job. No dataset fields are changed by this policy.
- `is_download_running()` and `queued_download_count()`: expose active/queued
  state without replacing the active transfer payload. The download slot stays
  occupied until `_cleanup_download_worker()` processes the finished signal,
  even if the underlying thread has already exited. This preserves FIFO order
  and worker ownership when jobs finish while more inputs are being queued.
  Dataset downloads remain on the
  worker thread and are presented by a non-modal Transfers dock with separate
  completed-file and byte/speed progress plus a per-file list. The dock remains
  visible with empty determinate controls when idle. `MainWindow` mirrors the lifecycle into the
  explorer's context-action state and prompts before quitting with an active
  download. Upload presentation retains its existing busy dialog.
- `start_upload(...)`: execute Hugging Face dataset upload from local dataset JSON inputs in a worker thread.
- `supports_safe_parquet_uploads()` and `find_missing_inputs(...)` gate Parquet
  conversion on a complete local dataset. `start_missing_inputs_download(...)`
  and `queue_missing_inputs_download(...)` use the shared background download
  slot to hydrate missing primary and ball
  inputs from pinned provenance. `MainWindow` owns the pending-upload state and
  resumes only after a second successful preflight.
- `start_model_import(...)`: inspect and cache one OpenSportsLib model repository
  through `_HfModelWorker`. Its started/progress/completed/failed/cancelled
  signals are routed by `MainWindow` to the active Settings draft; Settings
  widgets never hold the controller. `shutdown()` interrupts and waits for all
  dataset and model workers.
- Emits start/progress/byte-progress/completion/failure signals for UI wiring in
  `main_window.py`.
- `DatasetExplorerController.hfAssetDownloadRequested` carries the JSON path,
  sample ID, optional raw input path, requested local destinations, and project
  generation. `MainWindow.connect_signals()` owns the route to
  `HfTransferController`; successful results emit `mediaRefreshRequested` only
  for the still-current source. `MediaController.refresh_source()` reloads that
  source while preserving position and playing/paused state, without rebuilding
  the tree or changing selection.

### `InferenceController`
- Owns dynamic FIFO lanes keyed by stable `provider_id`. Each Local or remote
  provider has at most one worker while different providers may overlap.
  Providers are instantiated only when their requests reach the front.
- Aggregates runnable task models into provider-aware choices. Local discovery
  always runs; discovery covers every enabled remote and falls back to its last
  successful cached catalog after a transient failure. Identical model IDs
  remain distinct through their `(provider_id, model_id)` identity.
- Application Settings is the sole setup surface. Run requests contain an
  immutable snapshot of the selected provider endpoint and model configuration
  without administration credentials; the run dialog only chooses a model and
  runtime parameters. The Settings dialog has no global reset action because a
  reset would also discard the provider registry and Local model catalog;
  providers and models are removed only through their explicit row actions.
- `inference_settings.py` persists a permanent Local provider and UUID-backed
  remote providers with unique names and normalized URLs. Catalogs, refresh
  timestamps, and status share the provider record; administration
  tokens use a separate settings value. Legacy Local and single-server keys
  migrate only after the provider registry is saved successfully.
- The last successfully completed `(provider_id, model_id)` is stored per task and
  used as the preferred choice on the next run when still available.
- `enqueue_inference()`, `cancel_request()`, `cancel_all()`, `queue_snapshot()`,
  `queueChanged`, and `clear_queue_history()` form the queue interface.
  Immutable `InferenceQueueEntry` snapshots drive the Inference Jobs dock. Each
  entry includes a bounded immutable event timeline and repeated stage progress
  is coalesced. Terminal entries are stored without a count limit in
  application-wide SQLite until `clear_queue_history()` removes them or a
  successful `shutdown()` clears all job records. A timed-out shutdown retains
  them because the application remains open. Storage
  errors fall back to session-only history and emit `historyErrorChanged`. The
  jobs widget renders these snapshots in provider/algorithm and state/progress
  columns. Row selection owns the displayed event log, submitted/finished
  metadata, and the target of its external **Cancel Selected** action.
- Provider work runs in one `QThread` per active lane; `MainWindow` leaves
  navigation, editing, and further inference submission enabled. A generic
  post-provider cancellation check suppresses late results. A cancelling lane
  remains occupied until its worker exits before dispatching its next job.
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
  model metadata. Schema failures from OpenSportsLib remain authoritative;
  `parse_opensportslib_task()` adds a read-only shape diagnosis for its generic
  unsupported-schema error, and the resolver adds repository/revision/config
  context. No failed import creates a registry row. Only the two exact official
  localization repositories in `TRUSTED_LEGACY_HF_MODEL_IDS` may carry
  `trusted_legacy=True` through `ModelDescriptor` to `LocInferenceWorker`.
  Registry serialization revalidates that allowlist and revokes trust after a
  relevant manual edit.
- Manual Local registration stores a required config path and an optional
  weights path. `LocalInferenceProvider.validate_model()` checks both selected
  files and constructs the task-specific OpenSportsLib wrapper in the provider
  model-operation worker. The worker persists `status=ready` only after
  successful construction; failures persist as
  unavailable `status=failed` rows with the constructor error. An omitted
  weights file records `checkpoint_free=True`.
- Local adapters call public OpenSportsLib task classes. Missing native
  Description/Dense APIs are advertised as unavailable rather than emulated.
- Localization receives that dataset root in its request-scoped context and
  overwrites canonical `DATA.common.data_root` and test-split `source_path`
  only in the disposable runtime YAML; the test split's `annotation_path`
  points to the generated manifest. Imported or cached model configs remain
  unchanged.
- Remote execution uses the official OpenSportsLib server client for
  Classification and Localization requests with one or more videos, and
  one-video VQA requests. Single-video execution uses the direct upload path;
  multi-video samples use a disposable one-sample OSL manifest and the official
  manifest/media upload path with `remote_mode="full_test_set"`. The provider
  discovers the public model registry through `/health` and `/models`; all
  lifecycle states are exposed to Settings, while only healthy `ready` models
  are runnable. It translates the selected VAT head to and from OSL's `action`
  schema, preserves
  Localization clip/timeline offsets, and validates task-native results.
- Remote wrappers are constructed with only the server URL and registry model
  ID. Server-local IDs therefore never trigger local weights/config resolution.
  Initial VQA calls the updated direct `infer()` API and caches
  `last_remote_session_id`; follow-ups continue using the controller-owned
  session cache.
- Manual Local validation and authenticated remote registration or
  unregistration share one controller-owned model-operation worker. Settings emits intents and
  `MainWindow.connect_signals()` routes them. The admin token is persisted in
  application-local QSettings and copied into worker memory only for a registry
  request; it never enters logs, inference requests, or project data. Server
  actions are immediate. Enabled remote catalogs refresh when Settings or Run
  Inference opens, and Settings presents cached state while refresh runs.
- `InferenceController` owns the thread-safe VQA session cache and supplies it
  to request-scoped providers. Keys include normalized server, model, sample,
  real video path, size, and modification time. Entries expire after 25 minutes
  and are cleared on project generation, remote-setting changes, and shutdown.
  A first question uses `infer(video_path=..., question=...)` and caches
  `last_remote_session_id`; follow-ups reuse the video through
  `infer(session_id=...)`. HTTP 404/410 retries once by uploading afresh.
  Sessions are never conversational context or persisted project data.
- Remote wrapper calls cannot be interrupted server-side. Waiting cancellation
  becomes terminal immediately. Active cancellation signals the worker and
  keeps its provider lane in `cancelling` until the worker exits; only then can
  the next request for that provider start. The terminal cancellation is stored
  in job history. Official direct files and staged
  multi-file archives are memory-buffered, with no shared-root or resumable path.
- Mode controllers emit inference intent; `MainWindow.connect_signals()` adds
  canonical sample/schema context and routes results back. Mode controllers
  then emit ordinary mutation intents to `HistoryManager`.

## Business Rules

Streaming VQA is the sixth editor (tab 5), implemented by the panel-only
`StreamingVQAEditorController`. It emits sample-list mutation intents to
`HistoryManager.execute_streaming_vqa_update` and shared-timeline seek/marker
intents through `MainWindow.connect_signals()`. Its modal commits are complete
and atomic, with no inference or evidence. See [its contracts](streaming_vqa/README.md).
- Dataset JSON mutation must preserve undo/redo correctness.
- No-op mutation requests should not change stacks.
- Save/export normalizes temporal annotations using an explicit or already
  cached genuine origin; it must not scan a cold H5 input or invent an origin
  for relative-only samples.
- `_normalize_dataset_json()` already deep-copies canonical JSON; the write
  path mutates that copy directly. Samples without temporal annotations skip
  timeline-origin resolution. `cache_h5_timeline_origins()` accepts the
  evaluation worker's file-signature/origin pairs and reuses each only while
  its source file's size and modification time still match. Save/export passes
  `scan_h5=False`, so a missing or stale cache entry leaves relative temporal
  data unchanged instead of reading the H5 timestamp array.
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
