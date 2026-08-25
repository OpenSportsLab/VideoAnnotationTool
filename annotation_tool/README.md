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
  - Edit-menu actions are the single owners of the platform-standard undo and
    redo shortcuts; do not register parallel window shortcuts for them.
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
    Optional `UTC_time_start` sets the modality's absolute UTC origin at local playback position `00:00.000`. It accepts ISO-compatible timestamps such as `2022-12-03 13:27:59.461000`, `T` separators, `Z`, and explicit offsets.
  - `{ "type": "frames_npy", "path": "...", "fps": 2.0 }`
  - Read-time alias: `{ "type": "frame_npy", ... }` is normalized to `frames_npy`
  - `{ "type": "tracking_parquet", "path": "...", "fps": 2.0 }`
    `fps` is optional fallback timing used only when parquet timestamps are unusable.
    V1 supports the PFF/PFF-compatible tracking schema and renders a pitch-only preview.
  - `{ "type": "player_joints_h5", "path": "...", "ball_path": "..." }`
    Uses absolute UTC timestamps from `timestamp_utc` for playback timing and renders a 3D stickman preview. `ball_path` is optional and overlays ball XYZ from a separate H5 file.
  - `{ "type": "player_centroids_h5", "path": "...", "ball_path": "..." }`
    Uses absolute UTC timestamps from `timestamp_utc` for playback timing and renders a top-down player centroid preview. `ball_path` is optional.

### Synchronized multi-input playback

Selecting a sample loads every supported item in its `inputs` list into an adaptive two-column viewer grid. The shared playback controls drive all panes; selecting an input child or clicking a pane changes focus without unloading the other inputs.

For H5 joints and centroid inputs, the earliest usable `timestamp_utc` is normally the pane's absolute origin. An input-level `UTC_time_start` is authoritative for every modality and overrides backend timing when present. Naive values are interpreted as UTC and timezone-aware values are normalized to UTC. A malformed explicit value intentionally falls back to relative alignment and displays a warning instead of using backend UTC. The sample timeline covers the full union of all UTC ranges, and panes show an unavailable message before their origin or after their end. Inputs without an absolute UTC origin align local `00:00` to the shared timeline start and are labeled `Relative`. When UTC is available, the timeline displays both elapsed time and current UTC.

Audio from all audio-capable panes may play together. Each pane has its own mute control, while the timeline mute button temporarily mutes every pane without discarding the individual feed choices.

Right-click a playable viewer and choose **Go to start** or **Go to end** to seek the shared timeline to that modality's first or final frame. For UTC-capable inputs these positions include the modality's UTC offset; relative inputs start at shared elapsed zero. Every pane follows the seek and remains synchronized.

The same viewer menu provides **Set UTC start…** when no explicit override exists, or **Correct UTC start…** and **Remove UTC start** when it does. Set/correct treats the entered value as UTC at modality-local `00:00.000`. Removing an override restores backend-derived timing when available. Each effective change is undoable and preserves absolute annotation timestamps.

To correct an input's alignment visually, right-click its viewer and choose **Synchronize this modality**. The action is available when the sample has at least two playable inputs and at least one valid absolute UTC origin. Synchronization pauses the group and freezes the other panes at the current UTC anchor. The normal timeline and playback controls then operate only on the selected modality; the sync bar also provides exact previous/next-frame controls. Left/Right provide the same frame stepping, while the existing relative-seek controls continue to move by one or five seconds.

Choose **Apply** when the selected frame matches the frozen panes. The tool stores `UTC_time_start = anchor UTC - selected local time` with six fractional digits, reroutes the group to that same absolute anchor, and creates one undoable dataset edit. Localization events and dense captions with `timestamp_utc` keep that authoritative instant; only their projected timeline positions change when the earliest modality changes. Applying an equivalent UTC value is a no-op. **Cancel**, changing samples/projects, or closing the project exits the mode without changing the dataset. Both Apply and Cancel leave playback paused.
- Localization event: `{ "head": str, "label": str, "position_ms": int, "timestamp_utc": str? }`
- Dense event: `{ "position_ms": int, "timestamp_utc": str?, "lang": str, "text": str }`

For temporal annotations, a valid `timestamp_utc` is authoritative and `position_ms` is a compatibility value projected relative to the resolved sample timeline origin. New or edited annotations write both fields when UTC is available. Save/export promotes legacy `position_ms` annotations when a genuine sample UTC origin can be resolved. Relative-only samples continue to use `position_ms`; malformed timestamps are preserved and fall back to it.

Localization and Dense Description tables show resolvable annotations as `YYYY-MM-DD HH:MM:SS.mmm UTC`. Their Time cells accept ISO-compatible UTC edits; rows without usable UTC retain the relative `MM:SS.mmm` editor.
- Caption list (Description): `[ { "variant": str?, "lang": str, "text": str, ...optional } ]`
- Q/A list: `[ { "question": str, "answers": [str, ...] } ]`

## Conventions
- Signal-first cross-module communication; `main_window.py` wires interactions.
- Controllers should not own `MainWindow`.
- Mutation contract: push history only on effective diff (no-op edits do not add stack entries).
- Media routing/business decisions are centralized in `MediaController`.
- UI modules remain presentation-focused.
- Application media-control preferences use `QSettings`, are parsed by
  `media_control_settings.py`, and are applied/wired only by `MainWindow`;
  they never enter `DatasetExplorerController.dataset_json`.
- Dataset Explorer page size uses `QSettings`, is normalized by
  `explorer_settings.py`, and is applied through the explorer controller without
  mutating dataset JSON or routing media.

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
