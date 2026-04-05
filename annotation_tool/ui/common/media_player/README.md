# Localization Media Player Widget

This package contains the UI components responsible for video playback, timeline visualization, and transport controls within the **Localization (Action Spotting)** mode.

It is designed to handle frame-accurate video navigation and visual feedback for temporal events.

## 📂 Directory Structure

```text
media_player/
├── __init__.py      # Exports LocCenterPanel and assembles the components
├── preview.py       # Handles the QMediaPlayer and Video Surface
├── timeline.py      # Handles the zoomable Timeline and Event Markers
└── controls.py      # Handles Play/Pause, Seek, and Speed controls

```

---

## 🧩 Components Detail

### 1. `preview.py` (MediaPreviewWidget)

**Responsibility**: Core media rendering.

* **Video Output**: Wraps `QVideoWidget` to display the video content.
* **Audio Handling**: Explicitly initializes `QAudioOutput` to ensure compatibility with PyQt6 (prevents black screen issues on some platforms).
* **State Management**: Emits signals for position, duration, and playback state changes.
* **API**:
* `load_video(path)`: Loads a video file.
* `set_position(ms)`: Seeks to a specific timestamp.
* `set_playback_rate(rate)`: Adjusts speed (e.g., 0.5x, 2.0x).



### 2. `timeline.py` (TimelineWidget)

**Responsibility**: Temporal visualization and navigation.

* **Custom Slider**: Uses `AnnotationSlider` (subclass of `QSlider`) to paint colored markers on the groove representing spotting events.
* **Zoom Logic**: Supports zooming in/out to increase precision for short clips or view the entire video duration.
* **Auto-Scrolling**: The timeline automatically follows the playhead during playback. If the user drags the scrollbar manually, auto-scrolling pauses until the playhead catches up.
* **Interaction**: Dragging the slider handle emits seek requests to the player.

### 3. `controls.py` (PlaybackControlBar)

**Responsibility**: User input for navigation.

* **Transport Buttons**: Play/Pause, Stop.
* **Seeking**:
* Fine steps: +/- 1 second.
* Large steps: +/- 5 seconds.
* Clip Navigation: Jump to Previous/Next video in the project list.
* Event Navigation: Jump to Previous/Next annotated event.


* **Speed Control**: Buttons to toggle playback speed (0.25x to 4.0x).

### 4. `__init__.py` (LocCenterPanel)

**Responsibility**: Assembly.

* It imports the three widgets above and arranges them in a vertical layout (`QVBoxLayout`).
* This class is exposed to the main window as the "Center Panel" for the Localization interface.

---

## 🔄 Data Flow & Signal Wiring

The wiring between these components is primarily handled by the **LocalizationManager** (Controller), not inside this package. This ensures the View remains decoupled from the Logic.

**Typical Flow:**

1. **User Click**: User clicks "Play" in `PlaybackControlBar`.
2. **Signal**: `PlaybackControlBar` emits `playPauseRequested`.
3. **Controller**: `LocalizationManager` receives the signal and calls `MediaPreviewWidget.toggle_play_pause()`.
4. **Feedback**: `MediaPreviewWidget` updates the video state.
5. **Sync**: `MediaPreviewWidget` emits `positionChanged`, which is connected to `TimelineWidget.set_position()`, updating the slider UI.

## 🛠 Usage

To use this component in the main application layout:

```python
from ui.localization.media_player import LocCenterPanel

# Inside the main window setup
self.center_panel = LocCenterPanel()
layout.addWidget(self.center_panel)

```

## ⚠️ Notes

* **PyQt6 Requirement**: This package relies on `PyQt6.QtMultimedia`. Ensure your environment has the necessary codecs installed (e.g., K-Lite Codec Pack on Windows) if you encounter playback issues with specific video formats.
