# Controllers: Description

Description mode uses a single controller for editor + navigation responsibilities.

## Files

### `desc_editor_controller.py`

Owns Description editor behavior:

- editor signal wiring (`confirm_clicked`, `clear_clicked`)
- tree selection text refresh (`on_item_selected`)
- caption save/clear/reset flows
- undo/redo command creation (`CmdType.DESC_EDIT`)
- Description dataset explorer actions (`add/remove/filter/clear`)
- done-status refresh through the shared tree status path

## Notes

- Media load orchestration for Description selection is handled in `main_window.py`.
- JSON load/create/save/export remains handled by `controllers/common/dataset_explorer_controller.py`.
- `DatasetExplorerController` still routes panel signals, but delegates Description mode add/remove/filter/clear behavior to `DescEditorController`.
