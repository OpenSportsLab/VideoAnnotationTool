# Classification Media Player Widget

## Overview

This package (`ui/classification/media_player`) contains the UI components responsible for video playback and navigation within the **Classification** workflow of the SoccerNet Pro Analysis Tool.

It is designed to be the **Center Panel** of the classification interface. It separates the video rendering logic from the navigation control logic, assembling them into a unified widget.

## Directory Structure

```text
media_player/
├── __init__.py      # Assembles components and exports 'ClassificationMediaPlayer'
├── preview.py       # Handles video rendering, seeking, and the clickable slider
└── controls.py      # Contains the bottom navigation toolbar (buttons)

```

---

## Components

### 1. `ClassificationMediaPlayer` (in `__init__.py`)

**Role:** The main container widget exposed to the rest of the application.

* **Layout:** Vertical (`QVBoxLayout`).
* **Structure:**
1. **Top:** A `QStackedLayout` containing the `MediaPreview` (and a placeholder for future Multi-View grid).
2. **Bottom:** The `NavigationToolbar`.


* **Public Methods:**
* `show_single_view(path: str)`: Loads a video file into the player and brings the single-view widget to the front.
* `toggle_play_pause()`: Toggles the playback state of the internal player.


* **Exposed Attributes:**
It exposes buttons from the toolbar directly so external Controllers (like `NavigationManager`) can connect signals easily:
* `self.prev_action`
* `self.prev_clip`
* `self.play_btn`
* `self.next_clip`
* `self.next_action`
* `self.multi_view_btn`



### 2. `MediaPreview` (in `preview.py`)

**Role:** Handles the actual media playback logic using `PyQt6.QtMultimedia`.

* **Key Features:**
* **QAudioOutput Integration:** Explicitly sets up audio output to prevent video rendering issues (black screens) on certain platforms.
* **Custom Slider:** Uses `ClickableSlider` to allow users to jump to a specific timeframe by clicking anywhere on the bar (instead of just stepping).
* **Time Display:** Shows current position vs. total duration (e.g., `00:05 / 00:15`).
* **Auto-Loop:** Playback is set to infinite loop by default.



### 3. `NavigationToolbar` (in `controls.py`)

**Role:** A simple widget container for the playback control buttons.

* **Buttons:**
* `<< Prev Action`: Jump to the previous top-level action in the tree.
* `< Prev Clip`: Jump to the previous video file (if multiple views exist).
* `Play / Pause`: Toggle playback.
* `Next Clip >`: Jump to the next video file.
* `Next Action >>`: Jump to the next top-level action.
* `Multi-View`: (Toggle) Intended to switch between Single View and Grid View.



---

## Usage Example

Typically, this widget is integrated into the `MainWorkspace` dock-based layout.

**Instantiation:**

```python
from ui.classification.media_player import ClassificationMediaPlayer

# Create the player widget
player_widget = ClassificationMediaPlayer()

```

**Connecting Signals (in `viewer.py` or Controllers):**
The app logic connects directly to the exposed buttons:

```python
# In viewer.py -> connect_signals()

# Connect Play/Pause button
player_widget.play_btn.clicked.connect(self.nav_manager.play_video)

# Connect Navigation buttons
player_widget.next_action.clicked.connect(self.nav_manager.nav_next_action)

```

**Loading a Video:**

```python
# In NavigationManager
path = "/path/to/video.mp4"
player_widget.show_single_view(path)

```

## Dependencies

* **PyQt6.QtWidgets**: `QWidget`, `QVBoxLayout`, `QPushButton`, `QSlider`, etc.
* **PyQt6.QtMultimedia**: `QMediaPlayer`, `QAudioOutput`.
* **PyQt6.QtMultimediaWidgets**: `QVideoWidget`.

