# Description Annotation Panel

Package-style Description editor view used in the right dock for Description mode.

## Structure

```text
ui/description/annotation_panel/
├── __init__.py
├── description_annotation_panel.ui
└── README.md
```

## Responsibilities

- Load the Qt Designer UI (`description_annotation_panel.ui`).
- Expose Description editor widgets/signals used by controllers:
  - `caption_edit`
  - `confirm_btn`
  - `clear_btn`
  - `confirm_clicked`
  - `clear_clicked`

## Styling

QSS object names are preserved for existing styles:

- `descCaptionEdit`
- `descConfirmBtn`
- `descClearBtn`
