# Welcome Widget

This package contains the landing screen view for project entry points.

## Directory Structure

```text
welcome_widget/
├── __init__.py        # WelcomeWidget view and UI binding
├── welcome_widget.ui  # Designer-controlled layout
└── README.md
```

## Responsibilities

- `WelcomeWidget` loads the `.ui` file and applies welcome-page setup.
- The widget exposes action signals only:
  - `createProjectRequested`
  - `importProjectRequested`
  - `tutorialRequested`
  - `githubRequested`
  - `recentProjectRequested(str)`
  - `recentProjectRemoveRequested(str)`
- The widget renders recent datasets through:
  - `set_recent_projects(paths: list[str])`
  - per-row file name button (clickable open)
  - per-row folder path label (non-clickable)
  - per-row remove button (`×`) to delete from recents
- The widget does not perform routing/business logic.

## Recent Projects Behavior

- The recent list is view-only and signal-driven.
- Clicking the file name emits `recentProjectRequested(path)`.
- Clicking `×` emits `recentProjectRemoveRequested(path)`.
- Persistence is not handled in the widget; `AppRouter` stores recents via `QSettings`.
- Router persists all unique opened datasets (newest first, deduplicated); widget displays only the top 5.

## Notes

- Edit layout in `welcome_widget.ui`.
- Keep runtime behavior (logo load + signal wiring) in `__init__.py`.
