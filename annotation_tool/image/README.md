# Image Assets

## Role
Holds static image assets used by UI modules.

## Architecture Context
Assets are loaded at runtime through `utils.resource_path(...)`.

## Public Surface
- `logo.png`: used by `ui.welcome_widget.WelcomeWidget`.

## Key Functions and Responsibilities
- No Python functions in this module.
- Responsibility is static asset storage only.

## Business Rules
- Assets should remain immutable runtime resources.

## Conventions
- Keep file names stable to avoid UI loading regressions.
- Add new assets with clear, descriptive names.

## Tests
- Covered indirectly by welcome widget initialization and manual UI checks.

## Developer Knowledge
- Replace assets without changing filenames when possible to avoid code churn.
- Prefer reasonably compressed PNG assets to keep startup snappy.
