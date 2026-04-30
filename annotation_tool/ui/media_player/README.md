# Media Player UI

## Role
Provides the central video/timeline panel used across all annotation modes.

## Architecture Context
- `MediaCenterPanel` loads static controls from `media_center_panel.ui`.
- It hosts `QMediaPlayer`, `QAudioOutput`, `QVideoWidget`, and a frame-preview surface for rendering.
- Playback business policy (routing/restart guards/backend selection/error dialogs) remains in `MediaController`.

## Public Surface
### Main Classes
- `MediaCenterPanel`
- `AnnotationSlider`
- `FramePreviewLabel`

### Control Signals
- `seekRelativeRequested(int)`
- `stopRequested()`
- `playPauseRequested()`
- `muteToggleRequested()`
- `playbackRateRequested(float)`

### Timeline/Media Signals
- `seekRequested(int)`
- `positionChanged(int)`
- `durationChanged(int)`
- `stateChanged(object)`

### Public Methods
- `load_video(path)`
- `play()`, `pause()`, `stop()`, `toggle_play_pause()`
- `set_position(ms)`, `set_playback_rate(rate)`
- `set_mute_button_state(is_muted)`
- `set_duration(ms)`, `set_markers(markers)`
- `show_video_surface()`, `show_frame_surface()`, `clear_preview()`, `set_frame_image(image)`

## Key Functions and Responsibilities
- `_setup_media_player()`: initializes player/audio/video widget wiring.
- `_setup_timeline()`: initializes slider/scroll/zoom behavior.
- `_setup_controls()`: maps buttons to emitted control signals.
- `AnnotationSlider.paintEvent(...)`: draws marker lines on timeline.

## Business Rules
- UI emits control intents; controller decides route/playback policy.
- Marker rendering is view-only and mode-agnostic.

## Conventions
- Keep widget logic and presentation in this module.
- Keep playback decision logic in `MediaController`; backend-specific parsing/rendering lives under `controllers/media/`.

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
- `MediaCenterPanel` owns widget/player primitives, but route/restart logic belongs in `MediaController`.
- The panel stays backend-agnostic: internal backends push either Qt video output or raster images into the same preview area.
- The preview surface is backend-agnostic: Qt video output for `video`, raster frame rendering for `frames_npy`, and pitch rendering for `tracking_parquet`.
- Marker payload contract:
  list of dicts with at least `start_ms`, optional `color`.
- Marker color is supplied by the owning mode controller; the media player should render it without imposing mode-specific defaults.
- Keep control signal names stable (`playPauseRequested`, `muteToggleRequested`, etc.) to avoid wiring regressions.
- Timeline zoom/scroll behavior is subtle; validate follow-playhead behavior after changes.
