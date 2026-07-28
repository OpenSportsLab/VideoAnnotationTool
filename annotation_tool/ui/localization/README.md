# Localization UI

## Role
Provides the Localization right-panel plus adapters for spotting tabs, hand events, and smart events.

## Architecture Context
- Static layout comes from `localization_annotation_panel.ui`.
- Runtime adapters in `__init__.py` expose controller-friendly interfaces.
- Business logic is handled by `LocalizationEditorController`.

## Public Surface
### Main Class
- `LocalizationAnnotationPanel`

### Adapter Classes
- `_SpottingTabsAdapter`
- `_TableAdapter`
- `_SmartWidgetAdapter`
- `_AnnotationManagementAdapter`

### Panel Signals
- `tabSwitched(int)`
- `eventNavigateRequested(int)`

### Table Adapter Signals
- `annotationSelected(int)`
- `annotationModified(dict, dict)`
- `annotationDeleted(dict)`
- `annotationConfirmRequested(dict)`
- `annotationRejectRequested(dict)`
- `updateTimeForSelectedRequested(dict)`

## Key Functions and Responsibilities
- `LocalizationAnnotationPanel.__init__()`
  - Loads `.ui`, builds adapters, wires navigation buttons.
- `_SpottingTabsAdapter.update_schema(label_definitions)`
  - Rebuilds head tabs and spotting buttons.
  - Spotting buttons use the same deterministic label colors as table rows and timeline markers.
- `_TableAdapter.set_data(annotations)`
  - Displays editable event rows with full UTC timestamps when resolvable and relative time otherwise.
  - UTC edits accept ISO-compatible values while selection/seeking remains based on `position_ms`.
  - Includes a `Confidence` column for smart events.
  - Double-clicking a confidence cell opens a Yes/No/Cancel dialog to confirm/reject/ignore.
  - Applies deterministic per-label row colors so the table stays visually aligned with timeline markers.
- `_TableAdapter.set_timeline_origin(origin_utc)`
  - Supplies sample-scoped UTC display/edit context without coupling the panel
    to `MediaController`.
- `_SmartWidgetAdapter`
  - Emits smart inference range/confirm/clear requests.

## Business Rules
- Table edit emits old/new payloads; controller decides mutation validity.
- Tabs adapter manages head/label UX including add/rename/delete requests.
- Smart event actions are emitted as intent only; persistence remains in controller/history layer.
- Table row background color is derived from the same label-color mapping used for timeline markers.
- A malformed annotation `timestamp_utc` displays relative `position_ms`; an
  invalid UTC edit is rejected without emitting a mutation.

## Conventions
- Keep adapter APIs stable for controller calls/signals.
- Reuse shared UTC parsing/formatting helpers; keep relative table parsing local.

## Interactions
- Inbound from controller:
  - schema updates, event data refresh, time sync updates.
- Outbound to controller:
  - spotting/schema/table/smart intent signals.

## Tests
- `tests/gui/test_workflow_localization.py`
- `tests/gui/test_signal_decoupling_contract.py`

## Developer Knowledge
- Table adapter `annotationModified(old, new)` payload is part of controller contract; keep it unchanged.
- Spotting tab adapter controls UX-heavy behavior; keep context-menu and tab-switch semantics deterministic.
- If adding columns/fields, update parser/formatter helpers and controller event mapping together.
