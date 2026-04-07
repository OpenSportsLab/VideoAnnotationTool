# Localization UI

Localization right-panel UI package.

## Structure

```text
ui/localization/
├── __init__.py
├── localization_annotation_panel.ui
└── README.md
```

## Notes

- Main class: `LocalizationAnnotationPanel` (import path: `from ui.localization import LocalizationAnnotationPanel`).
- `.ui` stays standard-widget only.
- `__init__.py` attaches adapter behavior for spotting tabs, hand-events table, and smart inference widgets.
