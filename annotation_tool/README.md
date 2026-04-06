# Video Annotation Tool

This project is a professional video annotation desktop application built with **PyQt6**. It features a comprehensive **quad-mode** architecture supporting **Whole-Video Classification**, **Action Spotting (Localization)**, **Video Captioning (Description)**, and the newly integrated **Dense Video Captioning (Dense Description)**. 

With the latest update, the Classification mode now features **AI-Powered Smart Annotation**, allowing users to leverage state-of-the-art `opensportslib` models (e.g., MViT) to automatically infer actions via single or batch processing.

The project follows a modular **MVC (Model-View-Controller)** design pattern to ensure strict separation of concerns. It leverages **Qt's Model/View architecture** for resource management and a unified **Media Controller** to ensure stable, high-performance video playback across all modalities.

---

## 📂 Project Structure Overview

```text
annotation_tool/
├── main.py                     # Application entry point
├── viewer.py                   # Main Window controller (Orchestrator)
├── utils.py                    # Helper functions and constants
├── config.yaml                 # [NEW] Inference configuration for opensportslib models
├── __init__.py                 # Package initialization
│
├── models/                     # [Model Layer] Data Structures & State
│   ├── app_state.py            # Global State, Undo/Redo Stacks, & JSON Validation
│   └── project_tree.py         # Shared QStandardItemModel for the sidebar tree
│
├── controllers/                # [Controller Layer] Business Logic
│   ├── router.py               # Mode detection & Project lifecycle management
│   ├── history_manager.py      # Universal Undo/Redo system (Supports Batch Annotations)
│   ├── media_controller.py     # Unified playback logic (Anti-freeze/Visual clearing)
│   ├── classification/         # Logic for Classification mode
│   │   ├── class_annotation_manager.py # Manual label state management
│   │   ├── class_file_manager.py       # JSON I/O for Classification tasks
│   │   ├── class_navigation_manager.py # Action tree navigation
│   │   └── inference_manager.py        # [NEW] AI Smart Annotation (Single/Batch Inference)
│   ├── localization/           # Logic for Action Spotting (Localization) mode
│   ├── description/            # Logic for Global Captioning (Description) mode
│   └── dense_description/      # Logic for Dense Captioning (Text-at-Timestamp)
│       └── dense_editor_controller.py # Dense editor logic + explorer delegation
│
├── ui/                         # [View Layer] Interface Definitions
│   ├── common/                 # Shared widgets (Main Window, Sidebar, Video Surface)
│   │   ├── main_window.py        # Top-level UI (Stacked layout management)
│   │   ├── video_surface.py      # Shared Pure QVideoWidget + QMediaPlayer
│   │   ├── workspace.py          # Unified 3-column skeleton
│   │   └── dialogs.py            # Project wizards and mode selectors
│   ├── classification/         # UI specific to Classification
│   │   └── event_editor/         # Dynamic Schema Editor & [NEW] Smart Annotation UI
│   │       ├── dynamic_widgets.py  # Single/Multi label dynamic radio & checkbox groups
│   │       ├── editor.py           # Includes NativeDonutChart & Batch Progress UI
│   │       └── controls.py         # Playback control bar
│   ├── localization/           # UI specific to Localization (Timeline + Tabbed Spotting)
│   ├── description/            # UI specific to Global Captioning (Full-video text)
│   └── dense_description/      # UI specific to Dense Description
│       └── annotation_panel/
│           ├── __init__.py       # Loads DenseAnnotationPanel UI + table/input composition
│           └── dense_annotation_panel.ui
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

* **`localization_editor_controller.py`**: Logic for "Spotting" (mapping a label to a timestamp), schema management, table/timeline sync, and localization explorer delegation.
* **`dense_editor_controller.py`**: Logic for mapping free-text descriptions to timestamps, timeline sync, CRUD + undo/redo, and Dense-mode explorer add/remove/filter/clear delegation.

### 4. The View Layer (`/ui`)

* **`video_surface.py`**: A shared rendering component used by **every** mode to ensure consistent video performance.
* **`dense_annotation_panel.ui`**: Qt Designer file for Dense right-panel layout and editable table area.

---

## 🚀 Getting Started

1. **Select Mode**: Launch the app and use the "New Project" wizard to select one of the four modes.
2. **Import**: The `AppRouter` will automatically detect the correct modality if you import an existing JSON.
3. **Annotate**:
* In **Dense mode**, navigate to a point in the video, type your description in the right panel, and click "Add Description".
* Use the **Timeline** to jump between existing text annotations.
