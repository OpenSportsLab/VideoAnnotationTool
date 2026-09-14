# Streaming VQA controller

`StreamingVQAEditorController(panel)` owns manual question CRUD and presentation
snapshots. It never accepts another controller, accesses `dataset_json`, or
controls a player directly. `DatasetExplorerController` owns canonical state.

## Signals and wiring

- `sampleSelectionChanged` supplies the selected sample; raw array indices map
  sorted table rows back to canonical order, including imported invalid rows.
- `positionChanged` supplies the shared playhead; `timelineOriginChanged`
  supplies the sample UTC origin. Projection is presentation-only.
- `streamingVQAUpdateRequested(str, object)` carries sample ID and the complete
  proposed list to `HistoryManager.execute_streaming_vqa_update`.
- `mediaSeekRequested(int)` goes to `MediaController.set_position`.
- `markersUpdateRequested(object)` goes to the media panel, only while mode 5
  is active. Markers use projected ask times.

All routes live in `MainWindow.connect_signals()`. Add is wired to pause and
snapshot the runtime position before controller handling. Edit also pauses.
Neither dialog resumes playback or imposes a cutoff. Inference is disabled.

## Persistence and history

Shared pure policy in `streaming_vqa.py` validates IDs, complete questions,
distinct choices, correctness, and timing. Dialogs validate before returning;
the controller rejects invalid mutation intents. New IDs are UUIDs; IDs survive
reordering, question text is not an identity, and duplicates are not merged.

History uses the existing `SAMPLE_FIELD_EDIT` command and raw before/after
payloads. Every effective committed CRUD action creates one undo entry; no-ops
and cancellations create none. Deleting the last row removes the field and undo
restores its original presence and structure. Forward edits clear redo.

Save/export normalizes valid temporal rows with the existing helpers; malformed
imported rows and extra fields are preserved. Missing/duplicate IDs are repaired
only by an explicit dialog commit. `timestamp_utc` has the same authority and
projection rules as other temporal modes. UTC origin changes/removal and input
removal promote relative rows using the old genuine origin before projection
against the new origin. Negative absolute projections remain valid.

Viewing, mode switching, and programmatic table selection never mutate JSON or
seek media. User selection seeks. Refreshes and undo/redo remain lightweight.
If a filter hides the sample after a mutation, clear selection; do not choose
the next visible sample. No persisted drafts or evidence fields are introduced.

## Verification

`tests/gui/test_workflow_streaming_vqa.py` covers modal validation, IDs, CRUD,
save/export/reopen, history, invalid imports, filters, timeline behavior, UTC,
and multiview alignment. Run it with lifecycle, history-stack, signal-boundary,
Q/A, dense-description, and shared-playback regression suites.
