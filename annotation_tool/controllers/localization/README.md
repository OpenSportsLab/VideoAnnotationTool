# Localization Controllers

## Role
Implements Localization (action spotting) behavior, including schema management,
event CRUD, inference class mapping, and prediction review.

The shared local/remote path is owned by the central inference controller.
Remote range inputs may be clipped before upload and returned positions are
offset back onto the original sample timeline.

## Architecture Context
- `LocalizationEditorController` orchestrates Localization panel behavior.
- Constructor takes only the localization panel object.
- Controller does not own dataset model state (`self.model` is not used).
- Runtime sample/schema/action-list context is supplied through signal-slot wiring in `MainWindow.connect_signals()`.
- Emits schema/event mutation intents to `HistoryManager`.
- Local/Remote execution is owned by the central `InferenceController`; local
  execution calls OpenSportsLib directly through its provider.
- Local execution resolves device and loader capabilities in a temporary
  config. Missing CUDA selects CPU, and CPU or missing DALI changes DALI video
  datasets to their OpenCV equivalents without editing the registered model
  config.
- Emits media seek/marker/toggle intents instead of mutating media widgets directly.

## Public Surface
### Class
- `LocalizationEditorController`

### Outbound Signals
- `statusMessageRequested(str, str, int)`
- `saveStateRefreshRequested()`
- `itemStatusRefreshRequested(str)`
- `locHeadAddRequested(str)`
- `locHeadRenameRequested(str, str)`
- `locHeadDeleteRequested(str)`
- `locLabelAddRequested(str, str, str, int, bool)`
- `locLabelRenameRequested(str, str, str)`
- `locLabelDeleteRequested(str, str)`
- `locEventAddRequested(str, dict)`
- `locEventModRequested(str, dict, dict)`
- `locEventDelRequested(str, dict, int)`
- `locEventsSetRequested(str, object)`
- `locInferenceCommitRequested(str, object, object)`
- `mediaSeekRequested(int)`
- `markersUpdateRequested(object)`
- `mediaTogglePlaybackRequested()`

## Key Functions and Responsibilities
- `setup_connections()`
  - Wires spotting tabs, table actions, and the statistics request to controller behavior.
- `on_selected_sample_changed(sample)`
  - Loads selected sample snapshot into Localization panel.
- `on_timeline_origin_changed(sample_id, origin_utc)`
  - Projects authoritative UTC events onto the active sample timeline and gives
    the table its UTC formatting/editing context.
- `on_schema_context_changed(schema)`
  - Rebuilds schema-driven localization controls from runtime schema context.
- Head/label functions:
  - `_on_head_added`, `_on_head_renamed`, `_on_head_deleted`
  - `_on_label_add_req`, `_on_label_rename_req`, `_on_label_delete_req`
- Event functions:
  - `_on_spotting_triggered`, `_on_annotation_modified`, `_on_delete_single_annotation`
  - `_event_seek_position` applies the configured navigation pre-roll while
    clamping seeks to timeline zero; it never changes event data.
- Statistics functions:
  - `_show_statistics` and `_localization_statistics` compute current-sample
    counts and pass them to the panel for display.
- Prediction flows:
  - `_request_shared_inference`, `apply_shared_inference_result`,
    `on_inference_committed`, `_on_confirm_single_annotation`,
    `_on_reject_single_annotation`

## Business Rules
- Schema operations enforce duplicate/name validity checks.
- Event modify/delete requires event existence and valid selection.
- Label add flow can optionally inject an event at current playback time.
- Pause/resume around modal label dialogs is signal-driven.
- The controller gathers distinct nonempty classes from a completed run and
  always opens `LocalizationClassMappingDialog` once for that run. The run's
  original head is selected by default, while the user can choose any existing
  head or create a new one. Changing the existing destination rebuilds its
  class choices, prefills exact matches, and leaves unknowns on Skip. Cancel
  and all-skipped results emit no mutation intent.
- `locInferenceCommitRequested(str, object, object)` carries the target head,
  optional new-head labels, and predicted events grouped by sample. `MainWindow`
  routes it to `HistoryManager.execute_localization_inference_commit()`, then
  refreshes the current snapshot and pending-sample index.
- `HistoryManager` merges against canonical events, deduplicates by
  head/label/time, and commits all affected samples and an optional new
  `single_label` head in one dataset snapshot undo entry. No-op results add no
  entry; forward commits clear redo.
- Dataset snapshot undo/redo rebuilds the pending-sample index from canonical
  events after `DatasetExplorerController` restores the document.
- Applied predictions live in canonical `events[]` with
  `confidence_score` and `inference_model_id` until reviewed.
- New, moved, and inferred events write `timestamp_utc` plus `position_ms` when
  a genuine sample origin is available; relative-only samples keep `position_ms`.
- The shared run dialog supplies head, labels, range, model, and provider details.
  `MainWindow` keeps the last queued Localization `start_ms`/`end_ms` for the
  selected sample in memory. It restores them when reopening the run dialog,
  clears them on a different sample selection or project reset, and leaves them
  intact for runs whose model does not support a time range. The dialog payload's
  `supports_time_range` flag controls whether a queued run updates this memory;
  the flag and remembered range are not persisted in application settings or
  project JSON. Each request still carries its own effective range parameters.
- UTC-synchronized inference results are projected from the selected inputs'
  origin onto the whole-sample timeline before they enter the event list.
  Per-input offsets let the local adapter use the H5 origin when a tracking
  model ignores another selected modality.
- Runtime fallback supports both legacy (`dali`, `DATA.test.type`) and canonical
  (`DATA.common.runtime.loader_backend`) OpenSportsLib configuration shapes.
- `LocInferenceWorker` keeps model class order from canonical
  `DATA.common.classes` or legacy `DATA.classes`, falling back to the selected
  VAT head only when the model config provides no classes. Its request-scoped
  manifest uses an empty `events` list, so inference never treats a head label
  as ground truth for a different model. It retains predicted events at
  `position_ms: 0`. Both canonical and legacy temporary test dataloaders receive
  safe inference defaults (`batch_size`, `shuffle`, `num_workers`, `pin_memory`)
  for CPU fallback; the existing result mapping handles classes absent from the
  selected VAT head. Cached model configs and project JSON stay untouched.
- Accepting removes prediction metadata from the event; rejecting uses the
  tracked delete path. Manual edits invalidate pending rows.
- Single-row review selects the following row after refresh, or the preceding row
  when the reviewed row was last; ordinary selection signaling seeks playback.
- Previous/next navigation advances from the selected table row when present, so
  a pre-roll seek cannot repeatedly resolve back to the same event. With no row
  selected, navigation resolves the nearest event from the playhead.
- Main-window shortcuts invoke the panel's selected-row intent surface. The
  controller remains unaware of key bindings and `QSettings` shortcut values.
- `set_navigation_preroll_ms(int)` receives the normalized application setting
  from `MainWindow`; row selection and previous/next navigation emit the adjusted
  media seek while event timestamps remain canonical.
- Table confidence-cell confirmation prompt supports `Yes` (confirm), `No` (reject), `Cancel` (no-op).
- Rejecting an inferred row removes it from the review table.
- Missing classes open one mapping dialog for all distinct classes in the run.
- Shared local and remote localization results are filtered in
  `apply_shared_inference_result()` before class mapping and the single tracked
  commit. Request context carries `min_confidence` as a 0–1 fraction; numeric
  `confidence_score`, `confidence`, or `score` values below it are removed,
  while equal or unscored events stay. A fully filtered run emits a status
  message and no mutation intent. The Run dialog remembers its percent value
  in application `QSettings`; no threshold enters project JSON.
- Statistics include all schema labels (including zero counts), pending
  confidence-scored events, and observed labels missing from the schema. Invalid
  event objects without a usable head or label are excluded.
- Statistics are recomputed from the selected sample snapshot on every request
  and do not emit mutation or media intents.
- The panel's Evaluate intent reaches `MainWindow` through the Localization
  controller's `evaluationRequested` signal. `MainWindow` snapshots project
  JSON and opens the selection dialog without reading H5 timelines. The dialog
  caches a lightweight label summary per scope; interval position validation
  remains in the worker. After submission, `LocalizationEvaluationWorker`
  projects valid UTC events against each sample's timeline origin and scores
  them. It scans timelines only for eligible samples with timestamped events
  in the selected heads. H5 origin reads use the same chunked helper as the
  dataset explorer, run off the UI thread, and check cancellation between
  chunks. The worker returns file-signature/origin pairs for the explorer's
  session cache, avoiding another H5 read on save. A changed project generation
  or JSON content discards the result.
  The worker reads saved heads only and never emits a history mutation intent.
- `LocalizationEvaluationWorker.progress(int, str)` reports a 0–100 completion
  estimate and the current stage. `MainWindow` updates the progress dialog and
  an elapsed-time label once a second. The worker checks cancellation during
  H5 reads and large AP calculations.
- `localization_evaluation.py` splits verified samples into logical intervals,
  excludes unlabeled and excluded samples, and rejects selected-head events
  with missing labels or positions outside declared intervals. Intervals use
  half-open `[start_time_ms, end_time_ms)` boundaries. Sorted interval starts
  assign each event with a binary search, so interval preparation scales with
  events rather than every event/interval pair. It converts the dialog's
  ground-truth-to-prediction choices into the prediction-to-ground-truth map
  used for scoring and calls
  OpenSportsLib's sparse spotting AP helpers using canonical `position_ms` and
  millisecond tolerances. It scores all events in selected ground-truth classes,
  treats missing or invalid prediction confidence as 1.0, and omits classes
  without truth events from macro averages. The evaluation dialog lists ground-truth classes;
  each can select one observed prediction label or be skipped. Prediction
  labels cannot be reused because the inverse mapping would be ambiguous.
  Skipped ground-truth classes and unused prediction labels do not enter the
  metric input. For every selected tolerance, the report includes AP plus
  precision and recall after all prediction events have been matched.
  The overall precision and recall are class macro averages. Tight and loose
  mAP use OpenSportsLib's
  trapezoidal tolerance averaging over 1–5 and 5–60 seconds. Each selected
  tolerance has one AP column formatted as `AP% (Precision%/Recall%)`.
  `MainWindow` loads and saves the last submitted Whole project/Selected sample
  choice and both selected heads through `localization_settings.py`. Missing or
  renamed heads fall back to the current available choices. Mappings and report
  state remain transient, and no project JSON fields are added.
- OpenSportsLib's `LocalizationModel.evaluate()` is a model/config evaluation
  workflow that may run inference. Comparing two existing VAT heads uses
  `parse_ground_truth()`, `get_predictions()`, and
  `compute_average_precision()` directly. For classes with more than two
  million estimated prediction/truth comparisons per tolerance, VAT uses an
  indexed matcher with the same greedy matching and interpolation rules; this
  keeps large head comparisons responsive and permits progress/cancellation
  within each AP calculation. Tests compare its results against OpenSportsLib.

## Conventions
- Emit mutation intents; do not apply persisted mutation policy locally.
- Keep marker/table display in controller, widget layout in UI package.
- Timeline markers should reuse the same label-color mapping as the Localization table rows.
- Respect no-op guard behavior for unchanged edits.
- Keep constructor boundary clean: panel-only constructor.

## Interactions
- Inbound:
  - `DatasetExplorerController.sampleSelectionChanged -> on_selected_sample_changed`
  - `DatasetExplorerController.schemaContextChanged -> on_schema_context_changed`
  - `MediaController.playbackStateChanged -> on_playback_state_changed`
- Outbound:
  - Mutation signals -> `HistoryManager.execute_*`
  - Status/save/item refresh -> `main_window` shell handlers

## Tests
- `tests/gui/test_workflow_localization.py`
- `tests/gui/test_localization_inference_mapping.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Event identity:
  localization table edits rely on old/new event matching. A valid normalized
  `timestamp_utc` is the stable temporal key; use `position_ms` only for legacy
  or malformed annotations, alongside `head` and `label`.
- Projection contract:
  table rows and markers consume projected copies. Selection and playback must
  not mutate canonical annotation JSON.
- Dialog flows:
  keep pause/resume signal toggling symmetric (toggle before + after) when modal input is used.
- Schema edits and event edits are coupled:
  head/label renames must keep existing events coherent.
- Smart tab and hand tab behavior differs; when changing tab logic, verify marker behavior in both.
- Always keep no-op checks for unchanged event modifications.
