# Description Controller

## Role
Owns Description mode list/detail editor behavior for ordered sample-level captions.

Shared inference remains transient during review. Confirm appends the candidate
without inference metadata; reject is non-mutating. Existing captions are never
replaced by inference acceptance.

## Architecture Context
- `DescEditorController` is selection-driven and operates on the selected sample payload.
- It emits caption updates to `HistoryManager` and never mutates project lifecycle state.
- It depends only on the description panel object and consumes panel-level signals/methods (not child widgets directly).

## Public Surface
### Class
- `DescEditorController`

### Outbound Signals
- `clearMarkersRequested()`
- `captionsUpdateRequested(str, object)`

## Key Functions and Responsibilities
- `setup_connections()`
  - Connects panel-level caption change signal to autosave pipeline.
- `on_mode_changed(index)`
  - Tracks active mode and requests marker clear when Description is active.
- `on_selected_sample_changed(sample)`
  - Loads selected sample and populates editor text.
- `save_current_annotation()`
  - Merges selected-row `variant`, `lang`, and `text` changes into a copied full
    caption list, preserving unknown keys and emitting only on an effective diff.
- `add_caption()` / `delete_selected_caption()`
  - Mutate caption-list structure through the same whole-list request signal.
- `reset_ui()`
  - Clears current context and disables panel state.

## Business Rules
- Autosave debounce is 250 ms.
- Pending edits are flushed before row/sample switches and structural actions.
- No selected sample => no save.
- No effective captions diff => no mutation signal.
- Description flow emits caption-only updates (`captions` field).
- Caption order and unexposed caption keys are preserved.

## Conventions
- Keep list selection and draft merging local to controller.
- Use signals for all persistence side effects.
- Do not own dataset create/load/save/filter/remove behavior.
- Keep controller-panel boundary clean: use `DescriptionAnnotationPanel` API (`set_caption_text`, `get_caption_text`, `set_caption_editor_enabled`).

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
