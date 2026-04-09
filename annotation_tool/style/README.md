# Style Module

## Role
Stores global Qt stylesheet assets.

## Architecture Context
Loaded by the shell (`VideoAnnotationWindow.load_stylesheet`) and applied application-wide.

## Public Surface
- `style.qss`: global style definitions for widgets, docks, tables, controls.

## Key Functions and Responsibilities
- No Python functions in this module.
- `style.qss` responsibilities:
  - Visual consistency across panels.
  - State styling (`hover`, `pressed`, `disabled`).
  - Class/object-name based theme targeting.

## Business Rules
- Styling must not encode business logic.

## Conventions
- Target stable Qt object names and dynamic properties from UI modules.
- Prefer additive style rules over broad wildcard overrides.

## Tests
- Visual behavior validated indirectly by GUI workflow tests.

## Developer Knowledge
- When adding new styles, prefer class/object selectors over broad widget selectors.
- Keep QSS aligned with stable object names used in `.ui` files.
- Test dark-theme readability in dense/localization tables and timeline controls after style changes.
