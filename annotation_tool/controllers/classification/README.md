# Classification Controllers

Classification mode now uses a single mode controller plus helper services.

## Files

- `classification_editor_controller.py`
  - Single Classification mode controller.
  - Owns selection/media load, annotation save/clear, schema CRUD, clip navigation.
  - Owns Classification Dataset Explorer delegation (`add/remove/filter/clear/clear_workspace`).
  - Owns dynamic-label UI wiring for the classification panel.
- `inference_manager.py`
  - Smart inference helper service.
  - Triggered through `ClassificationEditorController`.
- `train_manager.py`
  - Training helper service.
  - Triggered through `ClassificationEditorController`.

## Notes

- Obsolete split controllers (`class_annotation_manager.py`, `class_navigation_manager.py`) were removed.
- Classification lifecycle I/O (create/load/save/export) remains in
  `controllers/common/dataset_explorer_controller.py` in this staged architecture.
