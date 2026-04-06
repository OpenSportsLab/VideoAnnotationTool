# Localization Annotation Panel

Package-style Localization editor view used in the right dock for localization mode.

## Structure

```text
ui/localization/annotation_panel/
├── __init__.py
├── localization_annotation_panel.ui
└── README.md
```

## Responsibilities

- Load the Qt Designer UI (`localization_annotation_panel.ui`).
- Compose hand/smart localization widgets in the panel containers.
- Expose controller-facing API:
  - `tabs`
  - `annot_mgmt`
  - `table`
  - `smart_widget`
  - `tabSwitched`

## Preserved Styling Hooks

- `spotting_label_btn`
- `spotting_time_lbl`
- `spotting_scroll_area`
- `spotting_add_btn`
- `spotting_tabs`
- `annotation_table`
- `smart_inference_box`
- `run_inference_btn`
