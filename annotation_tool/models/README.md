# 📦 Data Models & State Management

This directory now contains lightweight shared exports. The canonical persisted dataset state lives in `controllers/dataset_explorer_controller.py` as one `dataset_json` tree.

## 📂 Module Descriptions

### `__init__.py`
* Re-exports shared compatibility symbols such as `CmdType`.
* The tree model is defined with the dataset explorer panel widget, not in this package.

## 🔄 Data Flow
1. **DatasetExplorerController** owns `dataset_json`, normalizes it, and rebuilds runtime indexes for the tree/UI.
2. **Mode controllers** mutate sample fragments directly inside `dataset_json`.
3. **Serialization** writes the full `dataset_json` document back to disk.
