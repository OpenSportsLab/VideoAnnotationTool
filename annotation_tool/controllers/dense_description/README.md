# Controllers: Dense Description

Dense Description mode now uses a single controller:

## `dense_editor_controller.py`

`DenseEditorController` owns Dense-mode behavior end-to-end:

- Dense editor signal wiring and timeline sync
- Dense event CRUD with undo/redo command pushes
- Tree selection handling for Dense clips
- Dense clip/event navigation
- Dense panel reset lifecycle
- Dense-mode Dataset Explorer delegation:
  - `add_dataset_items()`
  - `remove_dataset_item(index)`
  - `filter_dataset_items(index)`
  - `clear_dataset_items()`
  - `clear_workspace()`

This replaces the old `DenseManager` split and keeps Dense mode aligned with
the Description controller architecture.
