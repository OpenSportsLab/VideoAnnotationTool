# Models Module

## Role
Compatibility-only package for shared exports.

## Architecture Context
Runtime and persisted dataset state are not owned here; they are owned by `DatasetExplorerController`.

## Public Surface
- `__init__.py`
  - Re-exports `CmdType` from `controllers.command_types`.

## Key Functions and Responsibilities
- No model classes currently implemented in this package.

## Business Rules
- Do not introduce parallel dataset ownership here without explicit architecture change.

## Conventions
- Keep this package minimal and compatibility-focused.

## Tests
- Indirectly covered by controller/history tests that import `CmdType`.

## Developer Knowledge
- Treat this package as compatibility-only unless architecture explicitly changes.
- If moving shared types here, avoid creating a second source of runtime state.
- Keep exports minimal to reduce import cycles.
