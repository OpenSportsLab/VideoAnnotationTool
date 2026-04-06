# Classification UI

Classification mode UI is package-based and Qt Designer driven.

## Structure

```text
ui/classification/
├── annotation_panel/
│   ├── __init__.py
│   ├── classification_annotation_panel.ui
│   └── README.md
└── README.md
```

## Notes

- `classification_annotation_panel.ui` is standard-widget only (fully editable in Qt Creator).
- Runtime dynamic schema widgets (single/multi-label groups) are created in
  `annotation_panel/__init__.py` and inserted into the `.ui` placeholder container.
- Public panel class remains `ClassificationAnnotationPanel`.
