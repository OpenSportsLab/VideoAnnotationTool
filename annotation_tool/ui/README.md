# User Interface (UI) Module

This directory contains the View layer for the application. UI code is responsible for widget composition, presentation, and signal emission. Business logic and routing are handled by `controllers/`.

## Current Structure

```text
ui/
├── common/                 # Shared UI packages used by all modes
│   ├── dataset_explorer_panel/
│   ├── media_player/
│   ├── welcome_widget/
│   └── dialogs.py
├── classification/         # Classification-specific editor UI
├── localization/           # Localization-specific editor UI
├── description/            # Description-specific editor UI
├── dense_description/      # Dense Description-specific editor UI
└── README.md
```

## Architecture

- The application workspace is composed in `main_window.py` (outside this `ui/` folder).
- The workspace uses shared common panels:
  - `common/dataset_explorer_panel/` for the left dock.
  - `common/media_player/` for the center panel.
  - mode-specific editor panels on the right.
- The welcome screen view is provided by `common/welcome_widget/` and wired by `controllers/common/welcome_controller.py`.

## Common Module Summary

### `common/dataset_explorer_panel/`

- `DatasetExplorerPanel` + `DatasetExplorerTreeModel`.
- Qt Designer `.ui` driven sidebar.
- Signals for add/remove/filter interactions.
- Controller pair: `controllers/common/dataset_explorer_controller.py`.

### `common/media_player/`

- `MediaCenterPanel`.
- Qt Designer `.ui` driven unified media/timeline/playback panel.
- Exposes direct media/timeline/playback API for managers/controllers.

### `common/welcome_widget/`

- `WelcomeWidget`.
- Qt Designer `.ui` driven welcome screen.
- Emits action signals (`create/import/tutorial/github`) only.
- Controller pair: `controllers/common/welcome_controller.py`.

### `common/dialogs.py`

- Shared dialogs used by router/controllers (project mode selection, picker dialogs, media error dialog).

## Mode Modules Summary

### `classification/`

- UI for whole-video classification.
- Main content lives in `annotation_panel/` (`ClassificationAnnotationPanel` + `.ui`).

### `localization/`

- UI for action spotting workflows.
- Main content lives in `annotation_panel/` (`LocalizationAnnotationPanel` + `.ui`).

### `description/`

- UI for global description workflows.
- Main content lives in `annotation_panel/` (`DescriptionAnnotationPanel` + `.ui`).

### `dense_description/`

- UI for timestamped text description workflows.
- Main content lives in `annotation_panel/` (`DenseAnnotationPanel` + `.ui`).

## Design Principles

1. Views should stay passive: emit signals, render state, avoid business logic.
2. Reusable cross-mode UI belongs under `ui/common/`.
3. Layout customization should prefer `.ui` files where available.
4. Controllers coordinate behavior between shared panels and mode editors.
