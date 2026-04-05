# 📍 Localization UI Module

This directory contains the user interface components specifically designed for the **Action Spotting (Localization)** task. In this mode, users identify specific timestamps (events) within a video timeline, rather than categorizing the whole video.

## 📂 Directory Structure

```text
localization/
├── panels.py           # High-level layout container for the Localization view
├── widgets/            # Specialized functional components
│   ├── dataset_explorer_panel.py # Left sidebar: Video list & project controls
│   ├── media_player.py     # Center area: Video player & timeline
│   └── event_editor.py     # Right sidebar: Event buttons & data table
└── __init__.py

```

---

## 📝 File Descriptions

### 1. `panels.py`

**Purpose:** Layout Management.
This file defines the `LocalizationUI` class, which acts as the main container. It uses a `QHBoxLayout` (Horizontal Box Layout) to assemble the three main working areas:

* **Left:** Clip Explorer
* **Center:** Media Player
* **Right:** Event Editor

It serves as the integration point where these distinct widgets are instantiated and arranged.

### 2. `widgets/dataset_explorer_panel.py` (Left Sidebar)

**Purpose:** Resource Navigation & Project Management.

* **Clip Tree:** Displays the list of video files available in the project. It handles filtering (e.g., showing only "Done" or "Not Done" clips) and visual status indicators (checkmarks).
* **Project Controls:** Integrates the shared `UnifiedProjectControls` (from `ui/common`), providing standard buttons for saving, loading, and exporting the project.

### 3. `widgets/media_player.py` (Center Area)

**Purpose:** Video Playback & Visualization.

* **`MediaPreviewWidget`**: A wrapper around `QVideoWidget` for displaying the video content.
* **`TimelineWidget`**: A custom-painted widget that represents the video duration horizontally. It supports:
* **Visual Markers**: Draws red lines where events have been spotted.
* **Zooming**: Allows expanding the timeline for precise frame selection.
* **Auto-scrolling**: Keeps the playhead in view during playback.


* **`PlaybackControlBar`**: Provides granular control, including frame stepping (`<< 1s`, `>> 1s`), variable playback speed (0.25x - 4.0x), and seeking.

### 4. `widgets/event_editor.py` (Right Sidebar)

**Purpose:** Data Entry & Modification.

* **`AnnotationManagementWidget`**: A tabbed interface allowing users to organize annotations by categories (Headers). Inside each tab, dynamic buttons allow users to "spot" an action at the current timestamp.
* **`AnnotationTableWidget`**: A table view listing all recorded events for the current video. It supports:
* **In-place Editing**: Users can double-click cells to modify timestamps or labels.
* **Selection Sync**: Clicking a row jumps the video player to that event's time.

