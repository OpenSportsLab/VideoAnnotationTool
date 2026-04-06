# 🎨 User Interface (UI) Module

This directory contains the **View layer** of the application's MVC architecture. It is responsible solely for graphical presentation and user interaction.

**Note:** No business logic or data manipulation is performed here. All user interactions (clicks, edits, playback controls) are emitted as **Qt Signals** to be handled by the `controllers` module.

## 📂 Directory Structure

The UI is organized by functional domain, with a robust **Common** library supporting four distinct annotation modes:

```text
ui/
├── common/               # Shared architecture (Main Window, Workspace Skeleton, Dialogs)
│   ├── main_window.py    # Top-level Stacked Layout orchestrator
│   ├── workspace.py      # Unified Dock-based Workspace (QMainWindow)
│   ├── video_surface.py  # Shared video rendering widget
│   └── ...
│
├── classification/       # [Mode 1] Whole-Video Classification
├── localization/         # [Mode 2] Action Spotting (Timestamps)
├── description/          # [Mode 3] Global Description (Captions)
└── dense_description/    # [Mode 4] Dense Description (Timestamped Text)

```

---

## 🧩 Modules Description

### 1. Common (`ui/common/`)

The backbone of the application, ensuring a consistent user experience across all modes.

* **`main_window.py`**: The application entry point. It manages a `QStackedLayout` to switch between the **Welcome Screen** and the four **Workspaces** without destroying state.
* **`workspace.py`**: Defines the `MainWorkspace`. This is a `QMainWindow` that hosts the Dataset Explorer (Left Dock), Media Player (Center), and the tabbed Annotation Editor (Right Dock).
* **`video_surface.py`**: A pure rendering widget wrapping `QMediaPlayer` and `QVideoWidget`. It handles video output while leaving playback logic to the controllers.
* **`dataset_explorer_panel/`**: The **Left Sidebar** (Dataset Explorer). Refactored to use **Qt Model/View** (`QTreeView`) for high performance, packaged with `__init__.py` + `.ui` for layout control.
* **`welcome_widget/`**: The **Welcome Screen** package with `__init__.py` + `.ui`; emits UI signals handled by `controllers/common/welcome_controller.py`.
* **`dialogs.py`**:
* `ProjectTypeDialog`: Updated wizard allowing selection of **Classification**, **Localization**, **Description**, or **Dense Description**.
* `FolderPickerDialog`: A custom file tree allowing multi-folder selection.



### 2. Classification (`ui/classification/`)

Implements the interface for **Whole-Video Classification** (assigning categories to an entire clip).

* **`media_player/`**: Standard player with basic seek controls.
* **`event_editor/`**: Dynamic form generation (Radio buttons/Checkboxes) based on the project Schema.

### 3. Localization (`ui/localization/`)

Implements the interface for **Action Spotting** (identifying specific timestamps).

* **`media_player/`**:
* Features the **Zoomable Timeline**, visual event markers, and frame-stepping tools.


* **`event_editor/`**:
* **Spotting Tabs:** Rapid-fire buttons for defining event categories.
* **Annotation Table:** A spreadsheet view for editing timestamps and labels.



### 4. Description (`ui/description/`) [NEW]

Implements the interface for **Global Captioning** (one text description per video).

* **`media_player/`**:
* **Composite Player:** Combines the video surface with a specialized navigation toolbar.
* **Behavior:** Defaults to **Infinite Loop** to allow repeated viewing while typing.


* **`event_editor/`**:
* **Text Input:** A large `QTextEdit` for free-form text.
* **Actions:** Simple "Confirm" and "Clear" workflow.



### 5. Dense Description (`ui/dense_description/`) [NEW]

Implements the interface for **Dense Captioning** (text descriptions anchored to specific timestamps).

* **`event_editor/`**:
* **Input Widget:** A specialized panel showing the current video time alongside a text input area.
* **Dense Table:** A subclass of the Localization table. It replaces the "Label" column with a "Description" column and auto-sizes to a **2:1:4 ratio** (Time : Lang : Text).


* **Reuse:** This mode reuses the **Localization Center Panel** (Timeline + Player) to allow precise navigation between text events.

---

## 🎨 Design Principles

1. **Passive View:** These classes do not modify data directly. They display data provided by the controller and emit signals (e.g., `confirm_clicked`, `removeItemRequested`) when the user acts.
2. **Unified Workspace:** All modes are now integrated into a single dockable workspace. This ensures that the Dataset Explorer and Media Player are always consistent across different annotation tasks.
3. **Composite Design:** Complex widgets (like the Description Player) are built by composing smaller, single-purpose widgets (VideoSurface + Controls + Slider) rather than monolithic classes.
4. **Dynamic Generation:** Where possible, forms and tables adjust their content dynamically based on the loaded JSON schema or data model.
