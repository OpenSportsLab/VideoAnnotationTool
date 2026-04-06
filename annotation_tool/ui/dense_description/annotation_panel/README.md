# Dense Annotation Panel

Package-style Dense Description editor view used in the right dock for Dense mode.

## Structure

```text
ui/dense_description/annotation_panel/
├── __init__.py
├── dense_annotation_panel.ui
└── README.md
```

## Responsibilities

- Load the Qt Designer UI (`dense_annotation_panel.ui`).
- Compose the dense editor input + table surface.
- Expose controller-facing attributes:
  - `input_widget` (`update_time`, `set_text`, `descriptionSubmitted`, `text_editor`)
  - `table` (`set_data`, `annotationSelected`, `annotationDeleted`, `annotationModified`)

## Styling Hooks

QSS hooks preserved from the old dense input widget:

- `class="dense_time_display"`
- `class="dense_desc_editor"`
- `class="dense_confirm_btn"`
