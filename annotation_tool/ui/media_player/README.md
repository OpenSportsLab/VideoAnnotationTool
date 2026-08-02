# Media Player UI

## Role
Provides the central grouped media/timeline panel used across all annotation modes.

## Architecture Context
- `MediaCenterPanel` loads static controls from `media_center_panel.ui`.
- `MediaCenterPanel` dynamically creates one `MediaViewerPane` per sample input.
- Each pane owns its `QMediaPlayer`, `QAudioOutput`, `QVideoWidget`, and raster-preview surface.
- Playback business policy (routing/restart guards/backend selection/error dialogs) remains in `MediaController`.
- `configure_playback_controls(speed_rates, seek_intervals)` rebuilds the two
  single-row button layouts. `speed_buttons` and signed-second `seek_buttons`
  are the value-keyed widget collections; rebuilding emits no media intent and
  must not change position or playback state.

## Public Surface
### Main Classes
- `MediaCenterPanel`
- `MediaViewerPane`
- `ViewerLayoutMode`: `SINGLE`, `MOSAIC`, or `TABS` presentation mode.
- `AnnotationSlider`
- `FramePreviewLabel`

### Control Signals
- `seekRelativeRequested(int)`
- `stopRequested()`
- `playPauseRequested()`
- `muteToggleRequested()`
- `playbackRateRequested(float)`
- `paneFocusRequested(str)`
- `paneMuteToggleRequested(str)`
- `paneSyncRequested(str)`
- `paneGoToStartRequested(str)`
- `paneGoToEndRequested(str)`
- `paneUtcStartSetRequested(str, str)`
- `paneUtcStartRemoveRequested(str)`
- `syncFrameStepRequested(int)`
- `syncApplyRequested()`
- `syncCancelRequested()`

### Timeline/Media Signals
- `seekRequested(int)`
- `positionChanged(int)`
- `durationChanged(int)`
- `stateChanged(object)`

### Public Methods
- `configure_viewers(sources, focused_path)`: rebuild the adaptive viewer grid.
- `focus_viewer(path)`: change pane focus without reloading playback.
- `set_viewer_layout(mode)`: reparent existing panes into the single, mosaic,
  or tab host without recreating media sessions.
- `viewer_layout()`: return the active `ViewerLayoutMode`.
- `set_sync_availability(mapping)`: configure context-menu eligibility/reasons.
- `set_navigation_availability(mapping)`: enable boundary navigation for playable panes.
- `set_sync_mode(active, selected_path)`: show/hide the synchronization bar and pane state.
- `update_sync_status(anchor, local_ms, duration_ms, proposed)`: update synchronization labels.
- `set_mute_button_state(is_muted)`
- `set_duration(ms)`, `set_markers(markers)`

## Key Functions and Responsibilities
- `_setup_media_player()`: initializes the scrollable viewer host/grid.
- `_setup_sync_bar()`: initializes frame-step, Apply, and Cancel controls.
- `_create_viewer_pane()`: creates a pane and forwards its intent signals.
- `_setup_timeline()`: initializes slider/scroll/zoom behavior.
- `_setup_controls()`: maps buttons to emitted control signals.
- `MediaViewerPane.contextMenuEvent(...)`: presents navigation, synchronization, and manual UTC-start intents.
- `AnnotationSlider.paintEvent(...)`: draws marker lines on timeline.

## Business Rules
- UI emits control intents; controller decides route/playback policy.
- Timeline, relative-seek, and annotation-navigation intents are authoritative
  group seeks and must remain stable while playback is active.
- `focus_viewer(path)` changes only pane contour state; it must not seek or alter
  playback state. In single and tab layouts, a non-empty focus also selects the
  matching visible pane.
- An empty focus path clears every pane contour. Loading from a parent sample
  row preserves the group's pre-selection playing/paused state and retains the
  currently displayed pane.
- Layout changes keep `MediaViewerPane` and controller session identities
  stable. Hidden panes remain loaded and synchronized.
- A user-selected modality tab emits `paneFocusRequested(path)` but does not
  route media or change Dataset Explorer selection.
- Synchronization pins single/tab presentation to the syncing modality and
  temporarily disables modality-tab switching.
- Marker rendering is view-only and mode-agnostic.
- Context-menu actions never seek or mutate data directly.
- Go to start/end is disabled for unplayable inputs and during synchronization mode.
- Synchronization eligibility and explanatory tooltips come from `MediaController`.
- Viewer UTC actions are dynamic: Set when no explicit override exists, or Correct/Remove when it does.
- Set/correct treats the entered value as modality-local `00:00.000`; remove
  requires confirmation and removes only the explicit override.

## Conventions
- Keep widget logic and presentation in this module.
- Keep playback decision logic in `MediaController`; backend-specific parsing/rendering lives under `controllers/media/`.
- Application settings provide already-validated rates and intervals through
  `MainWindow`; the panel owns only dynamic widget construction and intent
  emission. `1x` and Play/Pause remain mandatory.

## Interactions
- Inbound from controller:
  - mute state updates, marker updates, seek/playback updates.
- Outbound to controller:
  - playback/mute/seek/playback-rate intents.

## Tests
- `tests/gui/test_core_lifecycle.py`
- `tests/gui/test_dataset_explorer_regressions.py`
- Mode workflow tests that assert playback/marker behavior.

## Developer Knowledge
- `MediaCenterPanel` and its panes own widget/player primitives, but group clock,
  route/restart, UTC, and synchronization logic belong in `MediaController`.
- The panel stays backend-agnostic: internal backends push either Qt video output or raster images into the same preview area.
- Pane preview surfaces support Qt video, NPY frames, tracking pitches, and H5 joints/centroids.
- Marker payload contract:
  list of dicts with at least `start_ms`, optional `color`.
- Marker color is supplied by the owning mode controller; the media player should render it without imposing mode-specific defaults.
- Keep control and pane intent signal names stable; cross-module wiring belongs in `MainWindow.connect_signals()` or `MediaController` construction.
- Timeline zoom/scroll behavior is subtle; validate follow-playhead behavior after changes.
