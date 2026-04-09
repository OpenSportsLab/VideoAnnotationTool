# UI Module

## Role
Provides all QWidget classes, `.ui` bindings, and adapter surfaces for controller consumption.

## Architecture Context
- UI modules render state and emit intent signals.
- Controllers own business logic and persistence decisions.
- `main_window.py` wires UI <-> controller interactions.

## Public Surface
- `dialogs.py`: shared dialogs.
- `welcome_widget/`: landing page widget.
- `dataset_explorer_panel/`: tree/filter/header inspector panel.
- `media_player/`: center media timeline/player panel.
- `classification/`, `localization/`, `description/`, `dense_description/`: right editor panels.

## Key Functions and Responsibilities
- `__init__.py` files in each UI package:
  - load `.ui` files using `uic.loadUi(...)`.
  - expose stable controller-facing attributes/signals.
  - add adapter logic where needed (localization/dense tables, tabs, smart widgets).

## Business Rules
- UI should not own dataset mutation rules.
- UI should not bypass controller pathways for persistence.

## Conventions
- Keep `.ui` files mostly static layout.
- Put adapter/interaction glue in package `__init__.py`.
- Preserve controller-facing API stability (signal names, key widget aliases).

## Tests
- Mode workflow tests under `tests/gui/test_workflow_*.py`.
- Explorer-focused and lifecycle tests validate UI/controller behavior together.

## Developer Knowledge
- Keep UI module APIs stable:
  controllers and tests rely on specific attribute/signal names.
- If a widget alias changes (for example `caption_edit`), update controller usage and tests together.
- Adapter modules (`localization`, `dense_description`) are compatibility boundaries; avoid breaking their emitted signal payload shapes.
