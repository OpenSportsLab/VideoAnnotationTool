# UI: Localization

Localization right-panel UI is package-style and Qt Designer driven.

## Structure

```text
ui/localization/
└── annotation_panel/
    ├── __init__.py
    ├── localization_annotation_panel.ui
    └── README.md
```

## Notes

- `LocalizationAnnotationPanel` is loaded from `localization_annotation_panel.ui`.
- Spotting tabs, event table, and smart inference widgets are composed in
  `annotation_panel/__init__.py`.
- Legacy `event_editor/` child modules were removed as part of the consolidation.
