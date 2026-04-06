# Controllers: Description

Description mode uses a single controller for editor + navigation responsibilities.

## Files

### `desc_editor_controller.py`

Owns Description editor behavior:

- editor signal wiring (`confirm_clicked`, `clear_clicked`)
- tree selection text refresh (`on_item_selected`)
- caption save/clear/reset flows
- undo/redo command creation (`CmdType.DESC_EDIT`)
- done-status refresh through the shared tree status path

## Notes

- Media load orchestration for Description selection is handled in `main_window.py`.
- JSON load/save/export remains handled by `controllers/common/dataset_explorer_controller.py`.
