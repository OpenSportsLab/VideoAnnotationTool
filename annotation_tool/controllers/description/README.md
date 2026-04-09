# Description Controller

## Role
Owns Description mode editor behavior for sample-level captions.

## Architecture Context
- `DescEditorController` is selection-driven and operates on the selected sample payload.
- It emits caption updates to `HistoryManager` and never mutates project lifecycle state.

## Public Surface
### Class
- `DescEditorController`

### Outbound Signals
- `clearMarkersRequested()`
- `captionsUpdateRequested(str, object)`

## Key Functions and Responsibilities
- `setup_connections()`
  - Connects caption editor text changes to autosave pipeline.
- `on_mode_changed(index)`
  - Tracks active mode and requests marker clear when Description is active.
- `on_selected_sample_changed(sample)`
  - Loads selected sample and populates editor text.
- `save_current_annotation()`
  - Converts editor text into `captions` payload and emits update if changed.
- `reset_ui()`
  - Clears current context and disables panel state.

## Business Rules
- Autosave debounce is 250 ms.
- No selected sample => no save.
- No effective captions diff => no mutation signal.
- Description flow emits caption-only updates (`captions` field).

## Conventions
- Keep parsing/formatting local to controller.
- Use signals for all persistence side effects.
- Do not own dataset create/load/save/filter/remove behavior.

## Interactions
- Inbound:
  - `DatasetExplorerController.sampleSelectionChanged -> on_selected_sample_changed`
- Outbound:
  - `captionsUpdateRequested -> HistoryManager.execute_sample_captions_update`

## Tests
- `tests/gui/test_workflow_description.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Selection payload contract:
  `on_selected_sample_changed(sample)` expects a sample dict from `dataset_json["data"][i]` or invalid selection sentinel.
- Description persistence scope:
  this controller emits only `captions` updates; avoid introducing unrelated sample mutations here.
- Autosave:
  keep `_suspend_autosave` guard when setting editor text programmatically to prevent false writes.
- Backward compatibility:
  `current_action_path` is still referenced by tests; keep or migrate tests in lock-step if removing it.
