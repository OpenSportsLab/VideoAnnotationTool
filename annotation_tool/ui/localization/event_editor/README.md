# Event Editor Widget

## Overview

This module is responsible for the **Right Panel** of the Localization (Action Spotting) interface. It provides the primary mechanisms for users to:
1.  **Create Events**: "Spot" actions at specific timestamps using dynamic category buttons.
2.  **Manage Schema**: Add, rename, or delete annotation categories (Heads) and labels.
3.  **Edit Events**: View, sort, and modify existing events in a detailed table view.
4.  **Control History**: Access Undo/Redo functionality for the localization task.

## Directory Structure

```text
ui/localization/event_editor/
├── __init__.py             # Package entry point; assembles components into LocRightPanel.
├── spotting_controls.py    # Top section: Tabbed interface for action spotting buttons.
└── annotation_table.py     # Bottom section: Data grid showing the list of events.

```

## Components Breakdown

### 1. `__init__.py`

**Main Class:** `LocRightPanel`

* **Role**: The editor widget for Localization Mode, hosted as a tab in the main workspace.
* **Composition**:
* **Header**: Contains the "Annotation Controls" label and the **Undo/Redo** buttons.
* **Top Widget**: `AnnotationManagementWidget` (imported from `spotting_controls.py`).
* **Bottom Widget**: `AnnotationTableWidget` (imported from `annotation_table.py`).


* **Usage**: This class is instantiated within the `MainWorkspace` dockable layout as the "LOC" tab.

### 2. `spotting_controls.py`

**Role**: Handles the dynamic creation of buttons based on the JSON schema. It allows users to click a button to record an event at the current video timestamp.

**Key Classes:**

* **`SpottingTabWidget`**:
* A `QTabWidget` where each tab represents a **Head** (Category, e.g., "Pass", "Shot").
* Supports context menus on tabs to **Rename** or **Delete** heads.
* Contains a special `+` tab to add new heads dynamically.


* **`HeadSpottingPage`**:
* The widget inside each tab.
* Displays a grid of `LabelButton`s for each label defined in the schema.
* Includes an "Add new label" button to extend the schema on the fly.


* **`LabelButton`**:
* A custom `QPushButton` that emits signals for Right-Click (Context Menu) and Double-Click events.



**Signals:**

* `spottingTriggered(head, label)`: Emitted when a user spots an action.
* `headAdded`, `headRenamed`, `headDeleted`: Emitted when schema structure changes.

### 3. `annotation_table.py`

**Role**: Displays the list of recorded events for the currently selected video. It supports direct cell editing.

**Key Classes:**

* **`AnnotationTableModel` (`QAbstractTableModel`)**:
* The underlying data model connecting the UI to the list of events.
* Columns: **Time** (formatted `MM:SS.mmm`), **Head**, **Label**.
* Implements `setData` to allow users to double-click a cell and modify the time or label directly.


* **`AnnotationTableWidget`**:
* Wraps the `QTableView`.
* Handles row selection (syncs with the video player seek).
* Provides a context menu to **Delete** events.



**Signals:**

* `annotationSelected(position_ms)`: Emitted when a row is clicked (tells the player to seek).
* `annotationModified(old_data, new_data)`: Emitted after a cell edit (tells the Controller to push an Undo command).
* `annotationDeleted(event_item)`: Emitted via context menu.

## Interaction Flow

1. **Initialization**: The `LocalizationManager` calls `update_schema()` on the `spotting_controls` to build the tabs.
2. **Spotting**:
* User clicks a button in `HeadSpottingPage`.
* Signal bubbles up to `LocRightPanel` -> `LocalizationManager`.
* Manager grabs current player time and adds an event to the Model.


3. **Data Refresh**:
* The Model updates the `AnnotationTableModel`.
* The table refreshes to show the new row.


4. **Editing**:
* User edits a timestamp in the table.
* `AnnotationTableModel` validates the input.
* If valid, it updates the internal data and signals the Manager to record the change for Undo/Redo.



## Dependencies

* **PyQt6**: `QtWidgets`, `QtCore`, `QtGui`.
* **Project Utils**: Standard signal/slot mechanisms defined in the Controller layer.
