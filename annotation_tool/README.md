# Video Annotation Tool

## Role
Desktop PyQt6 application for video annotation across four modes:
- Classification
- Localization (action spotting)
- Description (sample-level captions)
- Dense Description (timestamped text events)

## Architecture Overview
The app is organized into three runtime layers plus shell composition:
- Shell composition: `main_window.py`
- Controller/business layer: `controllers/`
- View layer: `ui/`
- Styling/assets: `style/`, `image/`

The canonical persisted in-memory state is a single `dataset_json` owned by `DatasetExplorerController`.

## Submodule Responsibilities
- `main.py`
  - Entry point: initializes `QApplication` and opens `VideoAnnotationWindow`.
- `main_window.py`
  - Composition root and signal wiring.
  - Owns docks/tabs layout, menu actions, shortcuts, and shell-level feedback.
- `controllers/`
  - Dataset lifecycle, mutation/undo-redo, media playback control, mode-specific editor logic.
- `ui/`
  - Widgets/adapters, `.ui` loading, user-intent signal emission.
- `models/`
  - Compatibility exports only (`CmdType`).

## Core Runtime Flow
1. User creates or opens a dataset from shell actions.
2. `DatasetExplorerController` loads/normalizes JSON and populates tree/indexes.
3. Tree selection emits selection context to editors + media route request.
4. Editors render state and emit mutation intents.
5. `HistoryManager` applies tracked mutations and pushes undo commands.
6. Undo/redo replays command transitions and emits refresh intents.

## Data Contracts
- Project root object (`dataset_json`) includes (non-exhaustive):
  - `version`, `date`, `dataset_name`, `description`, `metadata`, `labels`, `data`
- Sample object (`dataset_json["data"][i]`) typically includes:
  - `id`, `inputs`, `labels`, `events`, `captions`, `dense_captions`
  - Classification smart prediction marker: `labels[head].confidence_score` (optional float)
- Input item:
  - `{ "type": "video", "path": "..." }`
  - `{ "type": "frames_npy", "path": "...", "fps": 2.0 }`
  - Read-time alias: `{ "type": "frame_npy", ... }` is normalized to `frames_npy`
- Localization event: `{ "head": str, "label": str, "position_ms": int }`
- Dense event: `{ "position_ms": int, "lang": str, "text": str }`
- Caption list (Description): `[ { "lang": str, "text": str, ...optional } ]`

## Conventions
- Signal-first cross-module communication; `main_window.py` wires interactions.
- Controllers should not own `MainWindow`.
- Mutation contract: push history only on effective diff (no-op edits do not add stack entries).
- Media routing/business decisions are centralized in `MediaController`.
- UI modules remain presentation-focused.

## Key Tests
- Architecture/wiring: `tests/gui/test_signal_decoupling_contract.py`
- Dataset lifecycle and routing: `tests/gui/test_core_lifecycle.py`, `tests/gui/test_dataset_explorer_regressions.py`
- History contract: `tests/gui/test_history_stack_contract.py`
- Mode workflows:
  - `tests/gui/test_workflow_classification.py`
  - `tests/gui/test_workflow_localization.py`
  - `tests/gui/test_workflow_description.py`
  - `tests/gui/test_workflow_dense_description.py`

## Non-goals
- This package README is architectural documentation, not a user tutorial.
- Per-class signal/method details live in submodule READMEs.

## Developer Knowledge
- Source of truth:
  `DatasetExplorerController.dataset_json` is the canonical persisted state in memory.
- Mutation rule:
  effective dataset changes should create exactly one undo command; no-op changes should create none.
- Wiring rule:
  cross-module behavior should be connected in `VideoAnnotationWindow.connect_signals()` rather than hard-coding controller-to-controller calls.
- Media rule:
  playback routing/state logic belongs in `MediaController`; editor and explorer modules should emit intent signals.
- Selection rule:
  tree selection drives editor refresh and media routing; avoid hidden side effects outside selection handlers.
- Safe extension checklist:
  add signal contract -> wire in `main_window.py` -> add no-op guard if mutating -> add/update GUI regression tests.
