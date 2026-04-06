# Classification Annotation Panel

This package contains the Classification right-side annotation panel in the same package style used by other modes.

## Files

- `__init__.py`: `ClassificationAnnotationPanel` + runtime dynamic label widgets + donut chart widget.
- `classification_annotation_panel.ui`: Qt Designer layout (standard widgets only).

## Notes

- The `.ui` defines all static panel structure (task header, schema row, tabs, smart/train controls, bottom action row).
- Dynamic schema heads/labels are generated at runtime into `label_container` using standard Qt widgets.
- Public surface kept for controller/tests:
  - widgets: `task_label`, `manual_box`, `tabs`, `confirm_btn`, `clear_sel_btn`
  - methods: `setup_dynamic_labels`, `get_annotation`, `set_annotation`, `reset_smart_inference`, `reset_train_ui`, `update_action_list`
  - signals: `annotation_saved`, `smart_confirm_requested`, `hand_clear_requested`, `smart_clear_requested`, `smart_infer_requested`, `batch_run_requested`, plus schema signals.
