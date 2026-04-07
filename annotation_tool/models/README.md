# 📦 Data Models & State Management

This directory contains the **Model** layer of the MVC architecture. It is responsible for data storage, state validation, and providing standard interfaces for the View layer (`ui/`) and Controller layer (`controllers/`).

## 📂 Module Descriptions

### 1. `app_state.py` (Core Logic)
* **Purpose:** The central repository for the application's runtime state.
* **Key Class:** **`AppStateModel`**
    * **Responsibility:**
        * Stores Project Metadata (Path, Task Name, Modalities).
        * Manages JSON Schema Definitions (`label_definitions`).
        * Stores Annotation Data (Classification labels & Localization events).
        * Manages the **Undo/Redo Stack**.
    * **Validation:** Contains logic to validate imported JSON structures (`validate_gac_json`, `validate_loc_json`).
* **Key Enum:** **`CmdType`**
    * Defines types of commands (e.g., `SCHEMA_ADD_LBL`, `LOC_EVENT_ADD`) used by the `HistoryManager` to track user actions.

### 2. `project_tree.py` (UI Data Model)
* **Purpose:** A specialized Qt Model for the Left Sidebar (Clip Explorer).
* **Key Class:** **`ProjectTreeModel`**
    * **Inheritance:** `QStandardItemModel`
    * **Responsibility:**
        * Adapts the raw data list into a hierarchical format suitable for `QTreeView`.
        * Handles standard Item data (Display Name, Icon) and User Roles (File Path).
        * Allows the UI to be decoupled from the raw list logic.
    * **Usage:**
        * Instantiated in `viewer.py`.
        * Shared across both Classification and Localization views.
        * Manipulated by Controllers (`NavigationManager`, `LocalizationEditorController`).

## 🔄 Data Flow
1. **Controllers** update `AppStateModel` (business data) and `ProjectTreeModel` (UI list data) simultaneously.
2. **Views** (`QTreeView`) automatically reflect changes in `ProjectTreeModel` via Qt signals (`rowsInserted`, etc.).
3. **Serialization** (Save/Export) reads directly from `AppStateModel`.
