# User Interface (UI) Module

This directory contains the View layer for the application. UI modules expose widgets, presentation behavior, and signals. Business logic remains in `controllers/`.

## Structure

```text
ui/
├── dialogs.py
├── welcome_widget/
├── dataset_explorer_panel/
├── media_player/
├── classification/
├── localization/
├── description/
└── dense_description/
```

## Conventions

- Shared shell widgets live directly under `ui/` (`welcome_widget`, `dataset_explorer_panel`, `media_player`, `dialogs.py`).
- Each mode package is flat and self-contained:
  - `__init__.py`
  - `<mode>_annotation_panel.ui`
  - `README.md`
- `main_window.py` composes the shell widgets and mode widgets.
- UI modules should stay passive: emit signals, render state, avoid domain logic.
