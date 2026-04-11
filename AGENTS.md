# AGENTS Guide (Compact)

## Purpose
Working contract for contributors/agents. Preserve decisions here unless explicitly changed.

## Product Scope
PyQt6 desktop annotation tool for OSL sports-video datasets.

Must support:
- Project lifecycle: create/open/close/save/export JSON.
- Dataset curation: samples, metadata, schema (`labels`).
- Modes: Classification, Localization, Description, Dense Description.
- Editing/review UX: tree + timeline + table + media controls + filter + undo/redo.

Data model target:
- Root: metadata + `labels` + `data`.
- Sample: `inputs` and task keys like `labels`, `events`, `captions`, `dense_captions`.

## Architecture
Layers:
- UI (`annotation_tool/ui/...`): presentation + intent signals.
- Controllers (`annotation_tool/controllers/...`): behavior/state orchestration.
- Composition (`annotation_tool/main_window.py`): only place for cross-module wiring.

Runtime owners:
- `DatasetExplorerController`: canonical in-memory `dataset_json`, lifecycle, tree/filter/selection.
- `HistoryManager`: tracked mutations + undo/redo authority.
- `MediaController`: playback route/state/mute authority.
- Mode controllers (`Classification`, `Localization`, `Description`, `Dense`): mode-local behavior; emit mutation/media intents.

Default signal flow:
1. UI emits intent.
2. Controller emits typed request signal.
3. `MainWindow.connect_signals()` routes to owner.
4. Owner mutates state and emits refresh/context.

## Hard Boundaries
- No controller may store/accept `main_window`.
- No direct controller-to-controller constructor coupling in scoped modules.
- No event bus.
- No `DatasetModelFacade`.
- No legacy aliases (`window.model`, `window.router`); use `window.dataset_explorer_controller`.
- Mode controllers should only receive their panel.
- Explorer/editor controllers must not use `QMediaPlayer` directly.
- Do not duplicate tracked mutation logic outside `HistoryManager`.

## Data and History Contracts
- Canonical document: `DatasetExplorerController.dataset_json`.
- Tracked edits flow through `HistoryManager.execute_*`.
- Effective mutation => exactly 1 undo entry.
- No-op mutation => 0 undo entries.
- Forward mutation clears redo.
- Undo/redo must restore structural JSON equality.

## Selection/Refresh/Playback Contracts
- Tab switch must not repopulate tree.
- Tab switch with same selection/path must not restart media.
- Undo/redo should prefer lightweight refresh over full rebuild when possible.
- If filter hides selected row: clear selection (do not auto-select first visible).
- Explicit user sample/input selection should ensure playback when needed.

## UX Decisions to Preserve
- No single-view vs multi-view creation prompt.
- No `is_multi_view` new-project branch.
- Description controller consumes selected `sample` and emits caption-only updates.
- Classification manual edits save immediately on effective change.
- Dense add remains explicit modal (`Add New Description`), edits table-driven.
- Mute control: icon button on right side of timeline row.

## Refactoring Rules
- Prefer simple, explicit logic.
- Keep one canonical implementation per operation.
- Delete legacy paths instead of adding shims.
- Keep constructors minimal/explicit.
- Remove unused functions after refactors.
- Remove redundant logic/helpers.

## Testing Discipline
For architecture, mutation, playback, or workflow changes, update/run relevant suites in the folder `tests/gui`. Always run relevant tests before considering work complete.

## PR/Agent Checklist
1. Controller boundaries preserved?
2. History 1-or-0 push rule preserved?
3. No unnecessary tree/media regressions?
4. New behavior wired through `MainWindow.connect_signals()`?
5. No legacy aliases/facades reintroduced?
6. Logic kept simple?
7. Unused functions removed?
8. Redundant logic removed and canonical path retained?
9. README/docs updated if public contract changed?
10. Relevant regression tests added/updated and run?
