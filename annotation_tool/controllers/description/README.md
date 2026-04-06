# 🧠 Controllers: Description

This directory contains the business logic for **Description** mode (Global Video Captioning).

Description mode now uses a single controller for both editor behavior and description-specific tree navigation.

## 📂 Files

### `desc_annotation_manager.py`

**Description Mode Controller (Editor + Navigation).**
Manages the right panel (caption text) and Description-specific navigation actions.

* **Key Responsibilities:**
* **Selection/Text Refresh:** Loads caption content for the currently selected tree item.
* **Q&A Formatting:** If JSON contains `questions`, formats into readable `Q: ... / A: ...` blocks.
* **Save/Flatten:** Stores edited text as caption entries and marks project state dirty.
* **Undo/Redo Integration:** Pushes `CmdType.DESC_EDIT` commands to the global history stack.
* **Tree Navigation Helpers:** Handles previous/next action and previous/next clip traversal.
* **UI Reset:** Resets Description editor state during project clear/close flows.

### `desc_file_manager.py`

**I/O Handler (legacy/auxiliary).**
Handles schema-oriented Description JSON load/export behavior.

* **Key Responsibilities:**
* Preserves Description-specific fields (`inputs`, `captions`, metadata) during I/O.
* Supports legacy data shapes when importing older caption datasets.
