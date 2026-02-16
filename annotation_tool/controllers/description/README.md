# 🧠 Controllers: Description

This directory contains the business logic for the **Description** mode (Global Video Captioning).

Unlike other modes, this controller set must handle **Multi-Clip Actions** (where one logical "Action" ID might consist of multiple video files/camera angles) and legacy **Q&A formatting**.

## 📂 Files

### `desc_navigation_manager.py`

**Playback & Navigation Logic.**
Manages the Center Panel (Video Player) and the Left Sidebar (Tree View).

* **Key Responsibilities:**
* **Media Control:** Wraps the shared `MediaController`. It implements the "Stop -> Clear -> Load -> Play" sequence to ensure smooth video transitions without artifacts.
* **Tree Navigation:** Handles logic for moving between **Actions** (logical items) vs. **Clips** (physical files within an action).
* **Dynamic Loading:** Resolves video paths based on the project's root directory.



### `desc_annotation_manager.py`

**Editor & Data Logic.**
Manages the Right Panel (Text Input).

* **Key Responsibilities:**
* **Q&A Formatting:** If the loaded JSON contains `questions`, it formats them into a readable "Q: ... A: ..." block in the text editor.
* **Flattening:** Upon saving, it consolidates the text into a single description block (unless strict schema enforcement is added later).
* **Undo/Redo:** Pushes `CmdType.DESC_EDIT` commands to the global history stack.
* **State Tracking:** Updates the tree icon (Checkmark/Empty) immediately after a save.



### `desc_file_manager.py`

**The I/O Handler.**
Manages the specific JSON schema for Global Captioning tasks.

* **Key Responsibilities:**
* **Multi-Clip Support:** Can parse JSON where one `id` has multiple entries in the `inputs` list. It ensures all related files are registered in the `ProjectTreeModel`.
* **Legacy Support:** Handles older JSON formats where captions might be split by questions.
* **Export:** Reconstructs the `inputs` array during export to ensure the output JSON matches the input structure (preserving `name`, `fps`, etc.).
