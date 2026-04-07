# Unified Media Center Panel

This package contains the shared center panel used by all modes. The panel is now built from a single Qt Designer UI file and one Python class.

## Directory Structure

```text
media_player/
├── __init__.py             # MediaCenterPanel (logic + direct public API)
├── media_center_panel.ui   # Designer-controlled layout
└── README.md
```

## Architecture

- `media_center_panel.ui` defines the visual structure:
  - video area
  - timeline row (time label, zoom buttons, scroll area)
  - playback control rows
- `MediaCenterPanel` in `__init__.py` loads the `.ui` with `uic.loadUi(...)` and wires runtime behavior:
  - `QMediaPlayer`, `QAudioOutput`, `QVideoWidget`
  - custom marker slider painting
  - zoom/auto-follow timeline behavior
  - playback button signal emissions

## Public API

`MediaCenterPanel` exposes direct methods/properties/signals for controllers and `main_window.py`:

- Media: `player`, `video_widget`, `load_video(path)`, `play()`, `pause()`, `stop()`, `set_position(ms)`, `set_playback_rate(rate)`
- Timeline: `set_duration(ms)`, `set_markers(markers)`, `seekRequested`
- Playback signals: `playPauseRequested`, `seekRelativeRequested`, `stopRequested`, `nextPrevClipRequested`, `nextPrevAnnotRequested`, `playbackRateRequested`
- Media signals: `positionChanged`, `durationChanged`, `stateChanged`

## Notes

- UI customizations should be done in `media_center_panel.ui`.
- Runtime behavior and signal wiring should remain in `__init__.py`.
