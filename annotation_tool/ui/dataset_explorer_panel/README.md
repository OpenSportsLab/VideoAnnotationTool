# Dataset Explorer Panel

This package contains the shared Dataset Explorer view used by all modes.

## Directory Structure

```text
dataset_explorer_panel/
├── __init__.py                 # DatasetExplorerPanel + DatasetExplorerTreeModel
├── dataset_explorer_panel.ui   # Designer-controlled sidebar layout
└── README.md
```

## Responsibilities

- `DatasetExplorerTreeModel` holds tree items and file-path metadata (`FilePathRole`).
- `DatasetExplorerPanel` loads the `.ui` with `uic.loadUi(...)`, binds model/view behavior, and exposes UI signals:
  - `addDataRequested`
  - `removeItemRequested`

## Notes

- UI layout and widget arrangement should be edited in `dataset_explorer_panel.ui`.
- Runtime behavior and signal/model wiring should stay in `__init__.py`.
