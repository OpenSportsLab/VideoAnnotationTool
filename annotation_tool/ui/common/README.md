# 🛠️ Common UI Components

This directory contains **shared interface widgets** that are used across all four modes of the application (**Classification, Localization, Description, and Dense Description**).

The goal of this module is to adhere to the **DRY (Don't Repeat Yourself)** principle, ensuring a consistent layout and user experience regardless of the active task.

## 📂 Files & Components

### 1. `workspace.py`

* **Class:** `MainWorkspace`
* **Purpose:** The modern, dock-based architecture providing a unified interface for all annotation modes.
* **Structure:** A `QMainWindow` featuring:
1. **Left Dock:** Dataset Explorer (`DatasetExplorerPanel`).
2. **Center Panel:** Generic Media Player with unified controls.
3. **Right Dock:** Tab-based Annotation Editor (CLS, LOC, DESC, DENSE).


* **Usage:** This widget instantiates the Left Panel automatically, while the Center and Right widgets are injected via the constructor.

### 2. `main_window.py`

* **Class:** `MainWindowUI`
* **Purpose:** The top-level container that orchestrates the **Screen Stack**.
* **Architecture:** Uses a `QStackedLayout` to switch between views without destroying them.
* **View Indices:**
* **Index 0:** Welcome Screen (`WelcomeWidget`)
* **Index 1:** Classification Workspace
* **Index 2:** Localization Workspace
* **Index 3:** Description Workspace (Global Captioning)
* **Index 4:** **[NEW]** Dense Description Workspace (Timestamped Captioning)



### 3. `dataset_explorer_panel/`

* **Class:** `DatasetExplorerPanel`
* **Purpose:** The standardized **Left Sidebar** for file navigation.
* **Key Features:**
* **Architecture:** Refactored to use **Qt Model/View** (`QTreeView`) instead of `QTreeWidget` for better performance and separation of data.
* **Structure:** Package-style module with `__init__.py`, `dataset_explorer_panel.ui`, and local README docs.
* **Integrated Controls:** Embeds `UnifiedProjectControls` at the top.
* **Filtering:** Provides a "Show All / Labelled / Unlabelled" filter combo box.
* **Context Menu:** Supports right-click actions (e.g., "Remove Item").



### 4. `video_surface.py`

* **Class:** `VideoSurface`
* **Purpose:** A lightweight, logic-free wrapper for video rendering.
* **Components:** Encapsulates `QMediaPlayer`, `QAudioOutput` (with volume preset to 100%), and `QVideoWidget`.
* **Role:** Acts strictly as the **View** layer for media. Playback logic (Play/Pause/Seek) is handled externally by the `MediaController` to prevent audio/visual desync.

### 5. `project_controls.py`

* **Class:** `UnifiedProjectControls`
* **Purpose:** A standardized 3x2 **Project Management Grid**.
* **Layout:**
* **Row 1:** `New Project`, `Load Project`
* **Row 2:** `Add Data`, `Close Project`
* **Row 3:** `Save JSON`, `Export JSON`


* **Signals:** Emits signals (`createRequested`, `saveRequested`, etc.) to be caught by the main Controller, keeping this widget purely presentational.

### 6. `dialogs.py`

* **Classes:**
* `ProjectTypeDialog`: The "New Project" wizard. Now updated to support **4 Modes**: Classification, Localization, Description, and **Dense Description**.
* `FolderPickerDialog`: A custom file dialog allowing **Multi-Folder Selection** via a `QTreeView` with checkboxes/click-toggle.



### 7. `welcome_widget.py`

* **Class:** `WelcomeWidget`
* **Purpose:** The landing screen displayed on application startup.
* **Actions:** Provides large, accessible entry points to "Create New Project" or "Import Project JSON".

---
