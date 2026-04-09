# Description UI

## Role
Provides the Description right-panel widget for sample captions.

## Architecture Context
- Layout is defined in `description_annotation_panel.ui`.
- `DescriptionAnnotationPanel` is a thin wrapper exposing a stable controller-facing editor reference.

## Public Surface
### Main Class
- `DescriptionAnnotationPanel`

### Exposed Attributes
- `caption_edit` (alias to `descCaptionEdit` from `.ui`)

## Key Functions and Responsibilities
- `DescriptionAnnotationPanel.__init__()`
  - Loads `.ui` and sets `caption_edit` alias for controller/test compatibility.

## Business Rules
- UI layer is passive; controller owns autosave and mutation behavior.

## Conventions
- Keep this module intentionally thin.
- Preserve alias compatibility (`caption_edit`) for controller usage.

## Interactions
- Inbound from controller:
  - text set/reset and enable/disable state.
- Outbound to controller:
  - plain text edit signals from `caption_edit`.

## Tests
- `tests/gui/test_workflow_description.py`

## Developer Knowledge
- Keep `caption_edit` alias stable; it is a compatibility surface for controller/tests.
- If layout IDs change in `.ui`, update alias mapping in `__init__.py` immediately.
