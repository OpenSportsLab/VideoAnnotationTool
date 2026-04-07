# Controllers: Dense Description

Dense Description mode now uses a single controller:

## `dense_editor_controller.py`

`DenseEditorController` owns Dense-mode behavior end-to-end:

- Dense editor signal wiring and timeline sync
- Dense event CRUD with undo/redo command pushes
- Data-ID based selection handling for Dense samples
- Dense sample/event navigation (media routed centrally by Dataset Explorer)
- Dense panel reset lifecycle

This replaces the old `DenseManager` split and keeps Dense mode aligned with
the Description controller architecture.

Dense sample lifecycle (add/remove/filter/clear) and JSON lifecycle
(load/save/export) are routed through `controllers/dataset_explorer_controller.py`.
