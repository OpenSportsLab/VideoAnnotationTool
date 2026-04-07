# Classification UI

Classification right-panel UI package.

## Structure

```text
ui/classification/
├── __init__.py
├── classification_annotation_panel.ui
└── README.md
```

## Notes

- Main class: `ClassificationAnnotationPanel` (import path: `from ui.classification import ClassificationAnnotationPanel`).
- `.ui` contains all static layout.
- Runtime dynamic schema widgets (single/multi-label groups) are injected into `.ui` placeholders from `__init__.py`.
