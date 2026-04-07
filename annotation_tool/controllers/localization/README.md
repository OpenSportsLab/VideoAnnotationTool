# Controllers: Localization

Localization mode now uses a single controller:

## `localization_editor_controller.py`

`LocalizationEditorController` owns localization behavior end-to-end:

- Data-ID based selection refresh for localization samples
- Head/category and label schema operations
- Event spotting CRUD with undo/redo command pushes
- Table selection/edit/delete and timeline marker sync
- Sample and annotation navigation (media routed centrally by Dataset Explorer)
- Smart inference flow integration via `loc_inference.py`

This replaces the old `LocalizationManager` split and aligns localization mode
with the Description/Dense single-controller architecture.

Dataset lifecycle actions (`add/remove/filter/clear`) are owned by
`controllers/dataset_explorer_controller.py`.
