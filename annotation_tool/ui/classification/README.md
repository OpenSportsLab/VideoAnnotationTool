# 🏷️ Classification UI Module

This directory contains the user interface components specifically designed for the **Whole-Video Classification** task. In this mode, users assign attributes (labels) to an entire video clip rather than specific timestamps.

The UI is deeply integrated with the new AI workflow, offering dynamic schema-driven manual annotation, AI smart predictions, and in-app model training.

## 📂 Directory Structure

```text
ui/classification/
├── panels.py               # High-level 3-column layout container
├── media_player/           # Center area components
│   ├── __init__.py         # Assembles the ClassificationMediaPlayer
│   ├── player_panel.py     # Combines the Shared VideoSurface with Slider controls
│   └── controls.py         # Playback & Navigation buttons (Next/Prev Clip)
├── event_editor/           # Right sidebar components
│   ├── __init__.py         # Assembles the ClassificationEventEditor
│   ├── editor.py           # Tabbed Command Center & Native Donut Chart
│   └── dynamic_widgets.py  # Dynamically generated Radio/Checkbox schema groups
└── __init__.py
```

---

## 📝 Module Breakdown

### 1. `panels.py`
**Purpose:** High-Level Layout Orchestration.

Defines the `ClassificationUI` class, acting as the main skeleton for the workspace. It utilizes a three-column horizontal layout to mount the core functional areas:
* **Left:** Shared `ClipListPanel` (imported from `ui.common` for tree navigation).
* **Center:** `ClassificationMediaPlayer` (from `media_player`).
* **Right:** `ClassificationEventEditor` (from `event_editor`).

### 2. `media_player/` (Center Area)
**Purpose:** Video Playback and Clip Navigation.

This module replaces the legacy player with a robust, unified media pipeline to eliminate playback artifacts.

* **`player_panel.py`**: Contains the `PlayerPanel`. This widget marries the unified, shared `VideoSurface` with a custom `ClickableSlider` and time labels. It exposes the underlying `QMediaPlayer` so the controller logic can safely orchestrate loading and playing without UI freezes.
* **`controls.py`**: Contains the `PlaybackControlBar`. Unlike Localization, which requires granular frame stepping, Classification provides high-level dataset navigation (e.g., `<< Prev Action`, `Next Clip >`).

### 3. `event_editor/` (Right Sidebar)
**Purpose:** Data Entry, Schema Management, and AI Workflows.

This module has been massively expanded from a simple manual entry form into a **Tabbed Command Center** handling three distinct workflows:

* **Tab 1: Hand Annotation (`dynamic_widgets.py`)**: 
  * Features a schema-driven UI. Instead of hardcoding categories, it reads the JSON schema and dynamically instantiates `DynamicSingleLabelGroup` (Radio Buttons) or `DynamicMultiLabelGroup` (Checkboxes).
* **Tab 2: Smart Annotation (`editor.py`)**: 
  * Hosts the AI inference interface. Includes Single/Batch inference controls and features a highly optimized, custom `NativeDonutChart` (built with `QPainter`) to interactively visualize model confidence scores.
* **Tab 3: Train (`editor.py`)**: 
  * A dedicated UI for fine-tuning models. Collects hyperparameters (Epochs, LR, Device) and provides a real-time console terminal to monitor the background training loop.

---

## 💡 Key Concepts

1. **Dynamic UI Generation**: The **Right Panel** adapts instantly to the dataset. If a user adds a new Category via the text input, the UI automatically constructs and mounts the corresponding radio/checkbox group.
2. **Tab-Aware Logic**: The bottom action buttons ("Confirm" and "Clear") dynamically alter their signals depending on whether the user is viewing the Hand Annotation tab or the Smart Annotation tab, ensuring manual and AI states remain isolated until confirmed.
