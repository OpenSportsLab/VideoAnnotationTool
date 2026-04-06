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
- The widget does not perform routing/business logic.

## Notes

- Edit layout in `welcome_widget.ui`.
- Keep runtime behavior (logo load + signal wiring) in `__init__.py`.
