# Description UI

## Role
Provides the Description right-panel widget for ordered sample caption lists.

Includes the shared bottom inference-review footer and pending-caption preview.

## Architecture Context
- Layout is defined in `description_annotation_panel.ui`.
- `DescriptionAnnotationPanel` is a thin wrapper exposing a stable controller-facing API.

## Public Surface
### Main Class
- `DescriptionAnnotationPanel`

### Exposed Attributes
- `caption_edit` (alias to the selected row's `descCaptionEdit` detail editor)

### Exposed Signal
- `captionTextChanged()`
- `captionMetadataChanged()`
- `captionSelectionChanged(int)`
- `captionAddRequested()`
- `captionDeleteRequested()`
- `inferenceConfirmRequested()`
- `inferenceRejectRequested()`

### Exposed Methods
- `set_caption_text(text: str)`
- `get_caption_text() -> str`
- `set_caption_editor_enabled(enabled: bool)`
- `set_captions(captions, selected_row)`
- `set_caption_fields(variant=..., lang=..., text=...)`
- `get_caption_fields() -> dict`
- `set_caption_detail_enabled(enabled: bool)`
- `set_pending_prediction(candidate)`

## Key Functions and Responsibilities
- `DescriptionAnnotationPanel.__init__()`
  - Loads `.ui`, sets `caption_edit` alias for compatibility, and re-emits text changes via `captionTextChanged`.
- Caption list/detail helpers
  - Render one compact summary per caption and expose the selected caption's
    `variant`, `lang`, and `text` fields without persistence logic.
- `set_caption_editor_enabled()`
  - Applies enabled/disabled state consistently to editor and panel.

## Business Rules
- UI layer is passive; controller owns selection flushing, autosave, and mutations.
- List rows preserve source order and summarize variant, language, and text.
- `InferenceReviewBar` is always the final layout widget and contains review
  actions only; execution starts from the Inference Jobs dock.

## Conventions
- Keep this module intentionally thin.
- Preserve alias compatibility (`caption_edit`) for tests and backward compatibility.

## Interactions
- Inbound from controller:
  - text set/reset and enable/disable via panel methods.
- Outbound to controller:
  - `captionTextChanged()`.

## Tests
- `tests/gui/test_workflow_description.py`

## Developer Knowledge
- Keep `caption_edit` alias stable; it is a compatibility surface for controller/tests.
- If layout IDs change in `.ui`, update alias mapping in `__init__.py` immediately.
