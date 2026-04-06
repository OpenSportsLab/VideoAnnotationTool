# UI: Description Mode

Description-mode UI is focused on the right-side text editor panel.  
The center media/timeline/playback UI is shared through `ui/common/media_player/`.

## Structure

```text
ui/description/
├── annotation_panel/
│   ├── __init__.py
│   ├── description_annotation_panel.ui
│   └── README.md
└── README.md
```

## Main View

- **Class:** `DescriptionAnnotationPanel`
- **Import path:** `from ui.description.annotation_panel import DescriptionAnnotationPanel`
- **Loaded from:** `annotation_panel/description_annotation_panel.ui`

## Exposed Surface

- Widgets:
  - `caption_edit`
  - `confirm_btn`
  - `clear_btn`
- Signals:
  - `confirm_clicked`
  - `clear_clicked`

QSS object names remain:

- `descCaptionEdit`
- `descConfirmBtn`
- `descClearBtn`
