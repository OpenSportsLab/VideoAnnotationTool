# SoccerNet Pro Annotation Tool

This project is a professional video annotation desktop application built with **PyQt6**. It features a comprehensive **quad-mode** architecture supporting **Whole-Video Classification**, **Action Spotting (Localization)**, **Video Captioning (Global Description)**, and **Dense Video Captioning (Dense Description)** tasks.

The project follows a modular **MVC (Model-View-Controller)** design pattern to ensure a clean separation of concerns. By utilizing a **Qt Model/View** architecture for data handling and a **Unified Media Controller** for playback, the tool provides a high-performance and race-condition-free environment for complex video labeling.

---

## 📂 Project Structure Overview

```text
annotation_tool/
├── main.py                     # Application entry point
├── viewer.py                   # Main Window controller (orchestrates UI & Logic)
├── utils.py                    # Helper functions and constants
├── __init__.py                 # Package initialization
│
├── models/                     # [Model Layer] Data Structures & State
│   ├── app_state.py            # Central state & strict JSON validation for all 4 modes
│   └── project_tree.py         # Shared QStandardItemModel for the Project Tree
│
├── controllers/                # [Controller Layer] Business logic
│   ├── router.py               # Global routing & project type auto-detection
│   ├── history_manager.py      # Universal Undo/Redo system
│   ├── media_controller.py     # Standardized playback logic (Load/Stop/Delay/Play)
│   ├── classification/         # Logic for Classification mode
│   ├── localization/           # Logic for Localization mode
│   ├── description/            # Logic for Global Captioning mode
│   └── dense_description/      # [NEW] Logic for Dense Captioning mode
│
├── ui/                         # [View Layer] Interface definitions
│   ├── common/                 # Shared widgets (VideoSurface, Workspace skeleton)
│   ├── classification/         # UI components for Video Classification
│   ├── localization/           # UI components for Action Spotting (Timeline-based)
│   ├── description/            # UI components for Global Captioning (Text-based)
│   └── dense_description/      # [NEW] UI components for Dense Captioning
│
└── style/
    └── style.qss               # Centralized Dark mode styling (ID-based)

```

---

## 🏗️ Core Architecture & Component Reuse

The application is designed for maximum **code reusability** and **UI consistency**. The architecture leverages inheritance and component composition across all four modes.

### 1. The Quad-Mode System

The application distinguishes between modes based on the annotation granularity and UI requirements:

| Mode | Task Type | Key UI Features | Data Structure |
| --- | --- | --- | --- |
| **Classification** | Global Labeling | Single View / Multi-view slider | Dictionary (Head -> Label) |
| **Localization** | Action Spotting | **Timeline**, Markers, Action Tabs | List of events (Head, Label, Time) |
| **Description** | Global Caption | Text Editor | Global text captions |
| **Dense Description** | Dense Caption | **Timeline**, Markers, **Text Input** | List of events (Text, Time) |

### 2. Cross-Mode Component Reuse

* **The Skeleton (`UnifiedTaskPanel`)**: All modes use a 3-column layout (Sidebar, Video Center, Editor Right).
* **The Project Tree**: All modes share `ProjectTreeModel` and `CommonProjectTreePanel`, ensuring the file list behaves identically across tasks.
* **The Media Engine**: All modes use `VideoSurface` for rendering and `MediaController` for robust playback, preventing "black screens" or "ghost frames."
* **Localization & Dense Description (Heavy Reuse)**:
* **Dense Description** reuses the `LocCenterPanel` from the Localization mode, which includes the specialized **Zoomable Timeline** and **Marker system**.
* **Dense Description**'s table model (`DenseTableModel`) inherits from `AnnotationTableModel`, simply overriding the columns to display "Text" instead of "Label."



---

## 📝 Detailed Module Descriptions

### 1. Models (`/models`)

* **`app_state.py`**: The "Source of Truth." It maintains the internal state for all four modes. It contains `validate_loc_json`, `validate_desc_json`, and `validate_dense_json` to ensure strict schema compliance.
* **`project_tree.py`**: Implements a standard Qt Model that stores file paths and natural-sorts clip names.

### 2. Controllers (`/controllers`)

* **`router.py`**: The "Traffic Cop." It detects the project type by inspecting the `task` field in the JSON (e.g., `dense_video_captioning`) and switches the UI to the correct index.
* **`media_controller.py`**: Manages the video lifecycle. It enforces a specific sequence (Stop -> Clear Source -> Load -> 150ms Delay -> Play) to ensure the GPU buffer is cleared between clips.
* **`dense_description/dense_manager.py`**: Manages the logic for dense captioning. It captures the current `position_ms` from the player when a description is submitted and updates the timeline markers.

### 3. User Interface (`/ui`)

* **`common/video_surface.py`**: A pure wrapper around `QVideoWidget`. It ensures volume is managed and rendering is consistent.
* **`localization/media_player/timeline.py`**: A custom-drawn widget that renders markers on a zoomable axis. It is used in both Localization and Dense Description modes.
* **`dense_description/event_editor/desc_input_widget.py`**: Specifically designed for Dense Description, providing a `QTextEdit` for long-form text instead of the predefined category buttons used in Localization.

---

## 🔄 Is Dense Description Reusing Localization Code?

**Yes.** The Dense Description mode was specifically designed to leverage the infrastructure of the Localization mode.

1. **Shared Center Panel**: It uses the same `LocCenterPanel` (Video + Timeline). When you add a text description, it appears as a marker on the timeline, exactly like an action spot in Localization mode.
2. **Shared Table Logic**: The right-panel table uses a modified version of the Localization table. The underlying logic for jumping to a timestamp when a row is clicked is preserved.
3. **Data Flow**: Both modes use a `position_ms` based event system. The primary difference is that Localization uses **discrete labels** from a schema, while Dense Description uses **free-form text**.

---

## 🚀 Getting Started

1. **Select Mode**: Upon creating a "New Project," choose between Classification, Localization, or Description (Global).
2. **Auto-Detection**: When importing a JSON, the tool will automatically detect if it is a **Dense Description** project based on the presence of `text` fields within the `events` list or the `task` key in the header.
3. **Annotation**:
* In **Dense Description**, navigate the video, type your description in the right panel, and click "Add Description" (or use Shortcut **'A'**) to mark the point.
* Use **Undo/Redo** to revert any text edits or timestamp changes.

