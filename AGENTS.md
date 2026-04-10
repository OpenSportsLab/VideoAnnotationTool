# AGENTS Guide

## Purpose
This file is the working contract for agents and contributors modifying this repository.
It summarizes the current architecture and the business decisions that must stay stable unless explicitly changed.

## Product Scope
The product is a PyQt6 desktop annotation workspace for OSL-format sports video datasets.
It supports the full edit loop for dataset curation:
- Create/open/close/save/export dataset JSON projects.
- Add/remove samples and manage dataset-level schema (`labels`) and metadata.
- Annotate videos in four task modalities:
  - Classification: sample-level single-label and multi-label heads.
  - Localization (action spotting): timestamped event annotations.
  - Description: sample-level captions / structured text.
  - Dense Description: event-level timestamped textual descriptions.
- Review and edit annotations through synchronized tree selection, timeline markers, tables, and media playback controls.
- Maintain annotation quality and safety with undo/redo history and filtering.

From the docs perspective, the data model target is the OSL JSON structure:
- Top-level dataset metadata + taxonomy (`labels`) + item list (`data`).
- Per-sample multimodal `inputs` and task-specific keys such as `labels`, `events`, `captions`, `dense_captions`.

## Architecture Snapshot
High-level layering:
- UI layer (`annotation_tool/ui/...`):
  - Loads `.ui` forms, owns widget composition, and emits user-intent signals.
  - Contains view adapters (table models, button adapters, etc.) but not dataset mutation policy.
- Controller layer (`annotation_tool/controllers/...`):
  - Implements business behavior and state transitions.
  - Converts UI intents to mutation requests and refresh events.
- Composition layer (`annotation_tool/main_window.py`):
  - Instantiates panels/controllers and wires all cross-module signal-slot connections.
  - Acts as the only composition root.

Core runtime ownership:
- `DatasetExplorerController`:
  - Canonical in-memory dataset document (`dataset_json`) owner.
  - Handles project lifecycle, tree/index/filter/selection, and emits selection/media intents.
- `HistoryManager`:
  - Canonical mutation engine for tracked operations.
  - Owns undo/redo replay and emits refresh intents after state changes.
- `MediaController`:
  - Canonical playback source/state owner.
  - Owns route/load/play/pause/seek/stop/mute decisions.
- Mode controllers:
  - `ClassificationEditorController`
  - `LocalizationEditorController`
  - `DescEditorController`
  - `DenseEditorController`
  - Own mode-local UI state and emit typed mutation requests to history.

Signal flow (default):
1. UI widget emits intent to its owning controller.
2. Controller emits typed request signal (mutation/media/status/etc.).
3. `MainWindow.connect_signals()` routes that signal to the owning target controller.
4. Owning controller updates state and emits refresh/context signals.
5. Dependent controllers/panels refresh from those signals.

## Hard Boundaries (Do Not Break)
High-level module coupling rules:
- Controllers do not own each other directly through constructor injection (scoped architecture).
- No controller should accept/store `main_window`.
- Cross-module coordination must happen through explicit Qt signal-slot wiring in `MainWindow.connect_signals()`.
- No centralized event bus abstraction.
- No `DatasetModelFacade`-style abstraction layer.
- No legacy aliases such as `window.model` / `window.router`; use `window.dataset_explorer_controller`.

UI vs Controller split:
- UI modules:
  - Presentation only (layout, widgets, local rendering helpers, intent signals).
  - Must not implement dataset lifecycle or persistence policy.
- Controllers:
  - Business rules, state transition orchestration, validation/no-op guards.
  - Emit/consume typed signals; avoid direct widget-to-widget coupling across modules.

Media boundary:
- Explorer and editor controllers must not import/use `QMediaPlayer`.
- `MediaController` is the only owner of playback source/state/mute logic.
- Other modules request media actions by signals only.

Mutation boundary:
- `HistoryManager` is the mutation + undo/redo authority for tracked dataset edits.
- Do not duplicate mutation implementations across explorer/editors/history.

## Data Ownership and Mutation Rules
- `dataset_json` in `DatasetExplorerController` is the canonical in-memory document.
- All tracked dataset mutations should flow through `HistoryManager.execute_*` slots.
- History contract:
  - Effective JSON mutation => exactly one undo entry.
  - No-op mutation => zero undo entries.
  - Forward mutation clears redo.
- Undo/redo must restore structural JSON equality.

## Selection, Refresh, and Playback Contracts
- Tab switch must not repopulate the dataset tree.
- Tab switch with unchanged selection/path must not restart media.
- Undo/redo should avoid full tree rebuild when lightweight refresh is sufficient.
- Filter edge case: if selected row becomes hidden, clear selection (do not force-select first visible).
- Selection-triggered routing should still ensure playback when user explicitly selects a sample/input and player is not already playing it.

## Current UX Decisions to Preserve
- No single-view vs multi-view project creation prompt.
- No `is_multi_view` workflow branch for new project behavior.
- Description controller consumes selected `sample` payload and emits caption-only updates.
- Classification manual annotation saves immediately on effective value change.
- Dense add flow is explicit modal add (`Add New Description`), while edits are table-driven.
- Media mute control is icon-based and placed at the right side of the timeline row.

## Module Responsibilities
### DatasetExplorerController
- Own: dataset lifecycle (create/open/save/close), tree/filter/selection, selection context emission, media routing intent emission.
- Do not own: per-mode annotation mutation policy.

### HistoryManager
- Own: forward mutation execution + undo/redo replay for tracked operations.
- Emit refresh intents; do not take over UI composition concerns.

### MediaController
- Own: source routing, play/pause/seek/stop/mute logic and state signals.
- Keep playback guard logic centralized here.

### Mode Controllers
- Own: mode UI behavior and local mode state.
- Emit typed mutation intents; avoid direct dataset mutation duplication.

## Refactoring Principles
- Prefer deleting legacy compatibility paths instead of adding shims.
- Prefer one canonical implementation per business operation.
- Keep constructors minimal and explicit.
- If logic duplicates across controllers, centralize it in the owner module (usually `HistoryManager` for mutations, `MediaController` for playback).
- Keep files smaller by extracting coherent helpers, not by adding extra orchestration layers.

## Testing and Change Discipline
When changing architecture or mutation/playback behavior, update and run relevant suites:
- `tests/gui/test_signal_decoupling_contract.py`
- `tests/gui/test_history_stack_contract.py`
- `tests/gui/test_dataset_explorer_regressions.py`
- `tests/gui/test_core_lifecycle.py`
- `tests/gui/test_workflow_classification.py`
- `tests/gui/test_workflow_localization.py`
- `tests/gui/test_workflow_description.py`
- `tests/gui/test_workflow_dense_description.py`
- `tests/gui/test_media_player_controls.py`

## PR/Agent Checklist
1. Did you keep controller boundaries (no `main_window`, no direct controller-to-controller constructor dependency in scoped modules)?
2. Did you preserve the 1-or-0 history push rule for mutations?
3. Did you avoid unnecessary tree repopulate/media restart side effects?
4. Did you wire new behavior through explicit signals in `MainWindow.connect_signals()`?
5. Did you avoid reintroducing legacy aliases/facades?
6. Did you update module README(s) if public behavior/contracts changed?
7. Did you add or update regression tests for new behavior?
