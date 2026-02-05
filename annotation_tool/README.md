# SoccerNet Pro Annotation Tool

This project is a professional video annotation desktop application built with **PyQt6**. It features a comprehensive tri-mode architecture supporting **Whole-Video Classification**, **Action Spotting (Localization)**, and **Video Captioning (Description)** tasks.

The project follows a modular **MVC (Model-View-Controller)** design pattern to ensure separation of concerns between data handling, business logic, and user interface. Recent updates have unified the UI architecture using a composite design pattern and migrated resource management to a robust **Qt Model/View** architecture.

## 📂 Project Structure Overview

```text
annotation_tool/
├── main.py                     # Application entry point
├── viewer.py                   # Main Window controller (orchestrates UI & Logic)
├── utils.py                    # Helper functions and constants
├── __init__.py                 # Package initialization
│
├── models/                     # [Model Layer] Data Structures & State
│   ├── __init__.py
│   ├── app_state.py            # Global Application State & Undo/Redo Stack & Data Validation
│   └── project_tree.py         # Shared QStandardItemModel for File Tree (MV Pattern)
│
├── style/                      # Visual theme assets
│   └── style.qss               # Dark mode stylesheet (default)
│
├── controllers/                # [Controller Layer] Business logic
│   ├── __init__.py
│   ├── router.py               # Routing logic (Project loading & mode switching)
│   ├── history_manager.py      # Universal Undo/Redo system
│   │
│   ├── classification/         # Logic for Classification mode
│   │   ├── annotation_manager.py
│   │   ├── class_file_manager.py
│   │   └── navigation_manager.py
│   │
│   ├── localization/           # Logic for Localization mode
│   │   ├── loc_file_manager.py
│   │   └── localization_manager.py
│   │
│   └── description/            # [NEW] Logic for Description/Captioning mode
│       ├── desc_annotation_manager.py  # Handles Q&A text formatting & saving
│       ├── desc_file_manager.py        # JSON I/O & Tree population for Description
│       └── desc_navigation_manager.py  # Video playback & tree navigation logic
│
└── ui/                         # [View Layer] Interface definitions
    ├── common/                 # Shared widgets & layouts
    │   ├── main_window.py      # Main UI Assembler (Stacks Views)
    │   ├── workspace.py        # Generic 3-Column Layout (UnifiedTaskPanel)
    │   ├── clip_explorer.py    # Universal Sidebar (Project Tree View)
    │   ├── project_controls.py # Unified control buttons (Save, Export, etc.)
    │   ├── dialogs.py          # Pop-up dialogs (Wizard, File Picker)
    │   └── welcome_widget.py   # Welcome screen
    │
    ├── classification/         # UI components for Classification
    │   ├── media_player/       # Video Player & Navigation controls
    │   └── event_editor/       # Dynamic Radio/Checkbox Schema Editor
    │
    ├── localization/           # UI components for Localization
    │   ├── media_player/       # Timeline & Custom Player
    │   └── event_editor/       # Spotting Interface & Annotation Table
    │
    └── description/            # [NEW] UI components for Description
        ├── media_player/       # Video Player optimized for Q&A review
        └── event_editor/       # Text-based Caption/Q&A Editor

```

---

## 📝 File & Module Descriptions

### 1. Root Directory (Core Infrastructure)

These files form the backbone of the application infrastructure.

* **`main.py`**: The bootstrap script. Initializes the `QApplication` and launches the main window.
* **`viewer.py`**: Defines the `ActionClassifierApp` (Main Window). It acts as the primary **Controller**, initializing the shared `ProjectTreeModel` and connecting UI signals to specific Logic Controllers (Classification, Localization, or Description).
* **`utils.py`**: Utility functions for file handling, natural sorting, and icon generation.

### 2. Models (`/models`)

The **Data Layer**. These files handle the application state, data structures, and validation logic. They are completely decoupled from the UI.

* **`app_state.py`**: The core Application State. Stores runtime data (`manual_annotations`, `localization_events`, `action_item_data`), defines Undo/Redo stacks (`CmdType`), and contains strict JSON schema validation logic for all three modes.
* **`project_tree.py`**: The **Qt Standard Item Model**. This is the data source for the project tree. It inherits from `QStandardItemModel` and manages the hierarchical data of clips and source files using standard Qt roles.

### 3. User Interface (`/ui`)

The **View Layer**. Contains PyQt6 widgets and layout definitions. The UI structure uses **Passive Views**—widgets generally do not contain business logic.

#### Common Components (`/ui/common`)

* **`main_window.py`**: The top-level UI container. Manages the `QStackedLayout` to switch between Welcome, Classification, Localization, and Description views.
* **`workspace.py`**: Defines `UnifiedTaskPanel`. A generic 3-column skeleton that embeds the shared `CommonProjectTreePanel`.
* **`clip_explorer.py`**: Defines `CommonProjectTreePanel`. The **Shared View** for the project list.
* *MVC Update*: Uses `QTreeView` to visualize the `ProjectTreeModel`.


* **`dialogs.py`**: Contains modal dialogs such as the **Project Creation Wizard** (now supports Description mode) and custom **Folder Picker**.
* **`project_controls.py`**: Unified control buttons (Save, Export, Add Video) used in the sidebar.

#### Classification Components (`/ui/classification`)

* **`media_player/`**: Contains the **Video Playback** widgets (Video Player, Slider, Action Navigation).
* **`event_editor/`**: Contains the **Annotation Interface** widgets (Dynamic Radio/Checkbox groups driven by Schema).

#### Localization Components (`/ui/localization`)

* **`media_player/`**: Contains the **Video Playback** widgets (Timeline, Custom Video Player).
* **`event_editor/`**: Contains the **Annotation Interface** widgets (Tabbed Spotting Interface, Annotation Table).

#### Description Components (`/ui/description`) [NEW]

* **`media_player/`**: Contains the **Video Playback** widgets tailored for captioning review (Preview Player, Playback Controls).
* **`event_editor/`**: Contains the **Caption Interface** widgets (Text Editor for Q&A/Descriptions, Confirm/Clear controls).

### 4. Controllers (`/controllers`)

The **Logic Layer**. Pure Python logic handling business rules, data manipulation, and bridging Models and Views.

#### Shared Controllers

* **`router.py`**: Handles project lifecycle (Load/Create/Close). Determines which mode to launch (Classification, Localization, or Description) based on JSON structure.
* **`history_manager.py`**: Manages the Command Pattern implementation for the Undo/Redo system.

#### Classification Sub-module (`/controllers/classification`)

* **`class_file_manager.py`**: Handles JSON I/O for classification tasks.
* **`navigation_manager.py`**: Manages video navigation and playlist logic.
* **`annotation_manager.py`**: Handles schema logic and saving user selections.

#### Localization Sub-module (`/controllers/localization`)

* **`loc_file_manager.py`**: Handles JSON I/O for localization tasks.
* **`localization_manager.py`**: Core logic for action spotting and timestamp recording.

#### Description Sub-module (`/controllers/description`) [NEW]

* **`desc_file_manager.py`**: Handles JSON I/O for captioning tasks. Populates the tree with `Action -> Inputs` structure and manages saving data back to disk.
* **`desc_navigation_manager.py`**: Manages file navigation and playback logic specific to description tasks (e.g., auto-playing the first clip of an action). Includes robust playback handling (Stop -> Load -> Delay -> Play) to prevent black screens.
* **`desc_annotation_manager.py`**: Handles the Q&A text formatting logic. Parses JSON `questions` and `captions` into a readable text block and flattens edits back into the data model upon confirmation. Supports auto-advance after saving.

### 5. Style (`/style`)

* **`style.qss`**: CSS-like definitions for the default **Dark Theme**.
