# Description UI

## Role
Provides the Description right-panel widget for sample captions.

## Architecture Context
- Layout is defined in `description_annotation_panel.ui`.
- `DescriptionAnnotationPanel` is a thin wrapper exposing a stable controller-facing API.

## Public Surface
### Main Class
- `DescriptionAnnotationPanel`

### Exposed Attributes
- `caption_edit` (alias to `descCaptionEdit` from `.ui`)

### Exposed Signal
- `captionTextChanged()`

### Exposed Methods
- `set_caption_text(text: str)`
- `get_caption_text() -> str`
- `set_caption_editor_enabled(enabled: bool)`

## Key Functions and Responsibilities
- `DescriptionAnnotationPanel.__init__()`
  - Loads `.ui`, sets `caption_edit` alias for compatibility, and re-emits text changes via `captionTextChanged`.
- `set_caption_text()` / `get_caption_text()`
  - Controller-facing text access without exposing widget internals.
- `set_caption_editor_enabled()`
  - Applies enabled/disabled state consistently to editor and panel.

## Business Rules
- UI layer is passive; controller owns autosave and mutation behavior.

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
