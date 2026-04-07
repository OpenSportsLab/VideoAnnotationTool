# Description UI

Description right-panel UI package.

## Structure

```text
ui/description/
├── __init__.py
├── description_annotation_panel.ui
└── README.md
```

## Notes

- Main class: `DescriptionAnnotationPanel` (import path: `from ui.description import DescriptionAnnotationPanel`).
- Exposed surface:
  - widgets: `caption_edit`, `confirm_btn`, `clear_btn`
  - signals: `confirm_clicked`, `clear_clicked`
- QSS object names remain unchanged:
  - `descCaptionEdit`
  - `descConfirmBtn`
  - `descClearBtn`
