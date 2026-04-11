# Welcome Widget UI

## Role
Provides the landing screen for project entry actions and recent-project rendering.

## Architecture Context
- `WelcomeWidget` is a passive view.
- `WelcomeController` handles routing and recent-project interactions.

## Public Surface
### Main Class
- `WelcomeWidget`

### Signals
- `createProjectRequested()`
- `importProjectRequested()`
- `tutorialRequested()`
- `githubRequested()`
- `recentProjectRequested(str)`
- `recentProjectRemoveRequested(str)`

### Public Methods
- `set_recent_projects(paths: list[str])`

## Key Functions and Responsibilities
- `_load_logo()`
  - Loads logo image from `image/logo.png`.
- `_setup_connections()`
  - Connects static UI buttons to widget signals.
- `_build_recent_row(path)`
  - Builds one recent-project row with open/remove actions.

## Business Rules
- Widget does not persist recents.
- Widget does not open/remove datasets directly.

## Conventions
- Keep recent list rendering deterministic and signal-based.
- Keep routing in controllers, not widget methods.

## Interactions
- Inbound from controller:
  - `set_recent_projects(...)` model-to-view update.
- Outbound to controller:
  - create/import/link/recent action signals.

## Tests
- Covered by lifecycle and decoupling tests indirectly.

## Developer Knowledge
- Recent list is purely view rendering; persistence is owned by dataset controller via settings.
- Keep recent row UX consistent:
  filename click opens project, remove button only removes from recents.
- External links are routed by `WelcomeController`; avoid embedding URL policy in the widget.
