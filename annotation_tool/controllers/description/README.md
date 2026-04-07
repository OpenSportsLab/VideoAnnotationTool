# Controllers: Description

Description mode uses a single controller for editor + navigation responsibilities.

## Files

### `desc_editor_controller.py`

Owns Description editor behavior:

- editor signal wiring (`confirm_clicked`, `clear_clicked`)
- Data-ID based selection text refresh (`on_data_selected`)
- caption save/clear/reset flows
- undo/redo command creation (`CmdType.DESC_EDIT`)
- done-status refresh through the shared tree status path

## Notes

- Media routing and sample lifecycle (`add/remove/filter/clear`) are handled in
  `controllers/dataset_explorer_controller.py`.
- JSON load/create/save/export remains handled by `controllers/dataset_explorer_controller.py`.
