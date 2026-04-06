# Controllers: Localization

Localization mode now uses a single controller:

## `localization_editor_controller.py`

`LocalizationEditorController` owns localization behavior end-to-end:

- Tree selection and media loading for localization clips
- Head/category and label schema operations
- Event spotting CRUD with undo/redo command pushes
- Table selection/edit/delete and timeline marker sync
- Clip and annotation navigation
- Smart inference flow integration via `loc_inference.py`
- Localization Dataset Explorer delegation:
  - `add_dataset_items()`
  - `remove_dataset_item(index)`
  - `filter_dataset_items(index)`
  - `clear_dataset_items()`
  - `clear_workspace()`

This replaces the old `LocalizationManager` split and aligns localization mode
with the Description/Dense single-controller architecture.
