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
├── models/                     # [Model Layer] Shared enums / compatibility exports
│   └── __init__.py
│
├── controllers/                # [Controller Layer] Business Logic
│   ├── command_types.py        # Shared undo/redo command enum
│   ├── history_manager.py      # Universal Undo/Redo system (Supports Batch Annotations)
│   ├── media_controller.py     # Unified playback logic (Anti-freeze/Visual clearing)
│   ├── dataset_explorer_controller.py # Canonical dataset_json owner + lifecycle flows
│   ├── welcome_controller.py   # Welcome screen actions + recent datasets wiring
│   ├── classification/         # Logic for Classification mode
│   │   ├── __init__.py
│   │   ├── classification_editor_controller.py # Unified classification mode controller
│   │   ├── inference_manager.py                # AI Smart Annotation helper
│   │   └── train_manager.py                    # Training helper
│   ├── localization/           # Logic for Action Spotting (Localization) mode
│   │   └── __init__.py
│   ├── description/            # Logic for Global Captioning (Description) mode
│   │   └── __init__.py
│   └── dense_description/      # Logic for Dense Captioning (Text-at-Timestamp)
│       ├── __init__.py
│       └── dense_editor_controller.py # Dense editor logic + explorer delegation
│
├── ui/                         # [View Layer] Interface Definitions
│   ├── dialogs.py                # Shared dialogs (project type, media errors, etc.)
│   ├── welcome_widget/           # Welcome screen package
│   ├── dataset_explorer_panel/   # Left-dock dataset explorer package
│   ├── media_player/             # Center media/timeline package
│   ├── classification/           # Classification right-panel package
│   ├── localization/             # Localization right-panel package
│   ├── description/              # Description right-panel package
│   └── dense_description/        # Dense Description right-panel package
│
└── style/                      # Visual theme assets
    └── style.qss               # Centralized Dark mode stylesheet
```
---

## 📝 Detailed Module Descriptions

### 1. Core Infrastructure

* **`main.py`**: Initializes the `QApplication` and the high-level event loop.
* **`viewer.py`**: The heart of the application. It instantiates all Managers, connects signals between UI components and Logic Controllers, and implements `stop_all_players()` to prevent media resource leaks during mode switching.
* **`dataset_explorer_controller.py`**: Owns the canonical `dataset_json` document, handles open/create/close/save/export flows, tracks recent datasets, and routes the selected sample to all editor controllers.
* **`media_controller.py`**: Manages the "Stop -> Load -> Delay -> Play" sequence to eliminate black screens and GPU buffer artifacts.

### 2. The Model Layer (`/models`)

* Persisted dataset content now lives in one in-memory `dataset_json` tree managed by `dataset_explorer_controller.py`.
* Runtime-only state stays outside that JSON tree: current selection, recent datasets, media playback state, and undo/redo stacks.

### 3. Modality Logic (`/controllers`)

* **`localization_editor_controller.py`**: Logic for "Spotting" (mapping a label to a timestamp), schema management, table/timeline sync, and localization explorer delegation.
* **`dense_editor_controller.py`**: Logic for mapping free-text descriptions to timestamps, timeline sync, CRUD + undo/redo, and Dense-mode explorer add/remove/filter/clear delegation.

### 4. The View Layer (`/ui`)

* Shared shell widgets live directly under `ui/`: `welcome_widget/`, `dataset_explorer_panel/`, `media_player/`, and `dialogs.py`.
* Each mode package is flat and self-contained (`__init__.py` + `.ui` + `README.md`).
* Example: `dense_description/dense_annotation_panel.ui` defines Dense right-panel layout and editable table area.

---

## 🚀 Getting Started

1. **Create Dataset**: Launch the app and use the "Create New Dataset" dialog. The four editor tabs stay available for every dataset.
2. **Import**: Load any compatible JSON. The app keeps all supported annotation blocks in one `dataset_json` document instead of switching project modes.
3. **Annotate**:
* In **Dense mode**, navigate to a point in the video, type your description in the right panel, and click "Add Description".
* Use the **Timeline** to jump between existing text annotations.
