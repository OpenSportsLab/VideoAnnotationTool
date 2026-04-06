# UI: Dense Description

Dense Description right-panel UI is package-style and Qt Designer driven.

## Structure

```text
ui/dense_description/
└── annotation_panel/
    ├── __init__.py
    ├── dense_annotation_panel.ui
    └── README.md
```

## Notes

- `DenseAnnotationPanel` is loaded from `dense_annotation_panel.ui`.
- Dense input and table behavior are composed in `annotation_panel/__init__.py`.
- Legacy `event_editor/` child modules were removed as part of the consolidation.
