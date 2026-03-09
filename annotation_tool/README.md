# SoccerNet Pro Annotation Tool

This project is a professional video annotation desktop application built with **PyQt6**. It features a comprehensive **quad-mode** architecture supporting **Whole-Video Classification**, **Action Spotting (Localization)**, **Video Captioning (Description)**, and the newly integrated **Dense Video Captioning (Dense Description)**.

The project follows a modular **MVC (Model-View-Controller)** design pattern to ensure strict separation of concerns. It leverages **Qt's Model/View architecture** for resource management and a unified **Media Controller** to ensure stable, high-performance video playback across all modalities.

---

## 📂 Project Structure Overview

```text
annotation_tool/
├── main.py                     # Application entry point
├── viewer.py                   # Main Window controller (Orchestrator)
├── utils.py                    # Helper functions and constants
├── __init__.py                 # Package initialization
│
├── models/                     # [Model Layer] Data Structures & State
│   ├── app_state.py            # Global State, Undo/Redo Stacks, & JSON Validation
│   └── project_tree.py         # Shared QStandardItemModel for the sidebar tree
│
├── controllers/                # [Controller Layer] Business Logic
│   ├── router.py               # Mode detection & Project lifecycle management
│   ├── history_manager.py      # Universal Undo/Redo system
│   ├── media_controller.py     # Unified playback logic (Anti-freeze/Visual clearing)
│   ├── classification/         # Logic for Classification mode
│   ├── localization/           # Logic for Action Spotting (Localization) mode
│   ├── description/            # Logic for Global Captioning (Description) mode
│   └── dense_description/      # [NEW] Logic for Dense Captioning (Text-at-Timestamp)
│       ├── dense_manager.py      # Core logic for dense annotations & UI sync
│       └── dense_file_manager.py   # JSON I/O specifically for Dense tasks
│
├── ui/                         # [View Layer] Interface Definitions
│   ├── common/                 # Shared widgets (Main Window, Sidebar, Video Surface)
│   │   ├── main_window.py        # Top-level UI (Stacked layout management)
│   │   ├── video_surface.py      # Shared Pure QVideoWidget + QMediaPlayer
│   │   ├── workspace.py          # Unified 3-column skeleton
│   │   └── dialogs.py            # Project wizards and mode selectors
│   ├── classification/         # UI specific to Classification
│   ├── localization/           # UI specific to Localization (Timeline + Tabbed Spotting)
│   ├── description/            # UI specific to Global Captioning (Full-video text)
│   └── dense_description/      # [NEW] UI specific to Dense Description
│       └── event_editor/
│           ├── __init__.py       # Right panel assembler for Dense mode
│           ├── desc_input_widget.py # Text input & timestamp submission
│           └── dense_table.py    # Specialized Table Model for Lang/Text columns
│
└── style/                      # Visual theme assets
    └── style.qss               # Centralized Dark mode stylesheet

```

---

## 📝 Detailed Module Descriptions

### 1. Core Infrastructure & Routing

* **`main.py`**: Initializes the `QApplication` and the high-level event loop.
* **`viewer.py`**: The heart of the application. It instantiates all Managers, connects signals between UI components and Logic Controllers, and implements `stop_all_players()` to prevent media resource leaks during mode switching.
* **`router.py`**: Features a heuristic detection engine that identifies project types from JSON keys (e.g., detecting `"dense"` tasks to trigger the Dense Description mode).
* **`media_controller.py`**: Manages the "Stop -> Load -> Delay -> Play" sequence to eliminate black screens and GPU buffer artifacts.

### 2. The Model Layer (`/models`)

* **`app_state.py`**: Maintains the "Source of Truth" for the application. It stores `manual_annotations` (Class), `localization_events` (Loc), and `dense_description_events` (Dense). It also contains strict JSON Schema validators for each task.
* **`project_tree.py`**: A `QStandardItemModel` used by all modes to display clips in the sidebar.

### 3. Modality Logic (`/controllers`)

* **`localization_manager.py`**: Logic for "Spotting" (mapping a label to a timestamp).
* **`dense_manager.py`**: **[NEW]** Logic for mapping free-text descriptions to timestamps. It handles the submission from the `DenseDescriptionInputWidget` and updates the timeline markers.
* **`dense_file_manager.py`**: Handles JSON persistence for dense tasks, ensuring the `text` and `position_ms` fields are properly serialized.

### 4. The View Layer (`/ui`)

* **`video_surface.py`**: A shared rendering component used by **every** mode to ensure consistent video performance.
* **`dense_table.py`**: A specialized view inheriting from the Localization table model. It replaces the "Label/Head" columns with "Lang/Description" while maintaining the same timestamp-jump functionality.
* **`desc_input_widget.py`**: Provides a `QTextEdit` for long-form text and an "Add" button that captures the exact current playback frame.

---

## 🔄 Reusability & Modality Comparison

The application is built on a "Composite Design" strategy. While each mode serves a different task, they share significant architectural DNA.

### Is Dense Description a reuse of Localization?

**Yes.** The Dense Description modality is essentially a **specialized evolution** of the Localization mode.

* **Shared Center Panel**: Both use the `LocCenterPanel`, which includes the zoomable `TimelineWidget` and `VideoSurface`.
* **Shared Data Logic**: Both are "Event-based" (data is tied to a `position_ms`) rather than "Clip-based".
* **Shared Table Interface**: The `DenseTableModel` is a direct subclass of `AnnotationTableModel`, inheriting all natural sorting and timestamp-parsing logic.

### Modality Feature Matrix

| Feature | Classification | Localization | Global Description | Dense Description |
| --- | --- | --- | --- | --- |
| **Primary Data** | Multi-choice Labels | Timestamped Labels | Global Video Text | Timestamped Text |
| **Center UI** | Multi-view Player | Timeline + Player | Slider + Player | Timeline + Player |
| **Right UI** | Schema Editor | Tabbed Spotting | Text Editor | Text Input + Table |
| **Code Base** | Unique | Shared with Dense | Unique | Shared with Loc |

---

## 🚀 Getting Started

1. **Select Mode**: Launch the app and use the "New Project" wizard to select one of the four modes.
2. **Import**: The `AppRouter` will automatically detect the correct modality if you import an existing JSON.
3. **Annotate**:
* In **Dense mode**, navigate to a point in the video, type your description in the right panel, and click "Add Description".
* Use the **Timeline** to jump between existing text annotations.


