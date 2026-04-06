# ⚙️ Controllers Module (Logic Layer)

This directory contains the business logic of the **SoccerNet Pro Annotation Tool**. following the **MVC (Model-View-Controller)** architecture, these scripts act as the bridge between the data (`models.py`) and the interface (`ui/`). They handle user input, data processing, file I/O, and application state management.

## 📂 Directory Structure

```text
controllers/
├── media_controller.py     # [NEW] Unified Video Playback Manager
├── history_manager.py      # Universal Undo/Redo logic
├── router.py               # Application routing and mode switching
├── classification/         # Logic specific to Whole-Video Classification
├── localization/           # Logic specific to Action Spotting (Timestamps)
├── description/            # Logic specific to Global Captioning (Text)
└── dense_description/      # Logic specific to Dense Captioning (Timestamped Text)

```

---

## 📦 Module Details

### 1. Core Controllers (Root)

These controllers provide foundational functionality used across the entire application to ensure stability and consistency.

* **`media_controller.py`**
* **Role**: The centralized video playback engine used by all modes.
* **Responsibilities**:
* **Robust State Management**: Implements a strict `Stop -> Clear -> Load -> Delay -> Play` sequence to prevent black screens and buffer artifacts.
* **Race Condition Prevention**: Uses an internal `QTimer` that is explicitly cancelled upon stop, preventing videos from starting in the background after a user has closed a project.
* **Visual Clearing**: Forces the `QVideoWidget` to repaint/update on stop, ensuring no "stuck frames" remain visible.




* **`router.py`**
* **Role**: The "Traffic Cop" of the application.
* **Responsibilities**:
* Handles the "Create Project" and "Load Project" flows.
* Analyzes input JSON files (keys like `events`, `captions`, `labels`) to automatically detect the project mode.
* Initializes the appropriate specific managers and switches the UI view.




* **`history_manager.py`**
* **Role**: The "Time Machine" (Undo/Redo System).
* **Responsibilities**:
* Implements the **Command Pattern** to manage the Undo/Redo stacks in `AppStateModel`.
* Executes operations and triggers the necessary UI refreshes (`_refresh_active_view`) for all four modes.





### 2. Classification Controllers (`controllers/classification/`)

Logic dedicated to the **Whole-Video Classification** task (assigning attributes to an entire video clip).

* **`class_file_manager.py`**: Handles JSON I/O and relative path calculations.
* **`navigation_manager.py`**: Manages the "Action List" (Left Panel), auto-play logic, and filtering.
* **`annotation_manager.py`**: Manages dynamic schema logic (Radio/Checkbox generation) and saves class selections.

### 3. Localization Controllers (`controllers/localization/`)

Logic dedicated to the **Action Spotting** task (pinpointing specific timestamps).

* **`localization_editor_controller.py`**:
* Owns localization editor behavior: tree selection/media load, schema/head/label operations, spotting CRUD, table sync, and smart inference flows.
* Owns localization navigation helpers (next/previous clip and annotation).
* Owns localization Dataset Explorer delegation for add/remove/filter/clear and clear-workspace reset.
* Keeps localization table/timeline/tree refresh aligned with shared undo/redo pathways.

Localization JSON lifecycle load/create/save/export remains routed through
`controllers/common/dataset_explorer_controller.py` in the current staged design.



### 4. Description Controllers (`controllers/description/`) [NEW]

Logic dedicated to the **Global Captioning** task (one text description per video action).

* **`desc_editor_controller.py`**:
* Owns Description editor behavior: selection-to-text refresh, save/clear actions, reset, and undo command creation.
* Owns Description navigation helpers: previous/next action and previous/next clip traversal.
* Owns Description-mode dataset explorer actions: add/remove/filter/clear and clear-workspace reset.
* Keeps tree done-status updates aligned with shared status refresh pathways.


* **`desc_file_manager.py`**:
* Manages JSON I/O specific to the captioning schema, ensuring `inputs` and `captions` fields are preserved correctly.



### 5. Dense Description Controllers (`controllers/dense_description/`) [NEW]

Logic dedicated to the **Dense Captioning** task (text descriptions anchored to specific timestamps).

* **`dense_editor_controller.py`**:
* Owns Dense editor behavior: timestamp/text sync, event create/update/delete, and undo command creation.
* Owns Dense tree-selection and navigation helpers (next/previous clip and event).
* Owns Dense-mode Dataset Explorer delegation for add/remove/filter/clear and clear-workspace reset.

Dense JSON lifecycle load/save/export remains routed through the shared
`controllers/common/dataset_explorer_controller.py` in the current staged design.
