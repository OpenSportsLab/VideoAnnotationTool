# 📝 UI: Dense Description Mode

This directory contains the user interface components specifically designed for the **Dense Description** mode.

In this mode, users annotate videos by providing **text descriptions at specific timestamps**. Unlike global description (one caption per video), this mode supports multiple, time-anchored events, making it a hybrid between Localization (timestamps) and Description (free text).

## 📂 Directory Structure

```text
ui/dense_description/
└── event_editor/
    ├── __init__.py           # The main Right Panel container
    ├── desc_input_widget.py  # The Input Area (Top half)
    └── dense_table.py        # The Event List (Bottom half)

```

---

## 🧩 Components

### 1. Right Panel Container (`event_editor/__init__.py`)

* **Class:** `DenseRightPanel`
* **Location:** Placed in the **Right Panel** of the Unified Workspace.
* **Purpose:** Acts as the main controller for the Dense Description side panel, stacking the input widget above the event table.

#### Key Features:

* **Layout Strategy:** Uses a vertical layout with a fixed width of `400px`.
* **Undo/Redo:** Integrated directly into the header for quick access.
* **Component Assembly:**
1. **Header:** "Dense Annotation" label + Undo/Redo buttons.
2. **Input:** Instance of `DenseDescriptionInputWidget` (Top).
3. **Table:** Instance of `AnnotationTableWidget` with a swapped-in `DenseTableModel` (Bottom).


* **Signal Rewiring:**
* Explicitly replaces the default `AnnotationTableModel` with `DenseTableModel`.
* Reconnects `itemChanged` signals to ensure edits in the table (e.g., changing text or time) propagate correctly to the backend.
* Reconnects selection signals so clicking a row jumps the video player to that timestamp.


* **Responsive Column Sizing:**
* Implements a custom `resizeEvent` and `_apply_dense_column_ratio`.
* Enforces a **2 : 1 : 4** width ratio for **[Time : Lang : Description]** columns, ensuring the description text always gets the most space.



---

### 2. Input Widget (`event_editor/desc_input_widget.py`)

* **Class:** `DenseDescriptionInputWidget`
* **Purpose:** The primary interface for creating new annotations or editing existing ones.

#### Key Features:

* **Time Display:** Shows the current video timestamp (e.g., `Current Time: 00:12.450`) to give context for the annotation.
* **Text Editor:** A large `QTextEdit` for multi-line free-text entry.
* **Submission:** A "Confirm Description" button that emits the `descriptionSubmitted` signal with the text content.
* **Programmatic Access:** Includes `set_text()` to populate the field when a user selects an existing event from the table (for editing).

---

### 3. Data Table (`event_editor/dense_table.py`)

* **Class:** `DenseTableModel` (Inherits from `AnnotationTableModel`)
* **Purpose:** Adapts the standard localization table to handle textual descriptions instead of categorical labels.

#### Key Modifications:

* **Columns:** Redefined to **[Time, Lang, Description]**.
* **Time:** The timestamp in `mm:ss` format.
* **Lang:** The language code (default `en`).
* **Description:** The full text content.


* **Editability:**
* Overrides `flags()` to explicitly ensure `ItemIsEditable` is true for all cells.
* Implements `setData()` to handle updates:
* **Column 0:** Parses time strings back to milliseconds.
* **Column 2:** Updates the free-text description.


* **Data Binding:** Directly maps to the underlying dictionary keys: `position_ms`, `lang`, and `text`.


### 🔄 Interaction Flow

1. **Create:** User pauses video -> Types text in `Input` -> Clicks "Confirm" -> New row added to `Table`.
2. **Edit Text:** User clicks row in `Table` -> `Input` is populated with text -> User edits & Confirms -> `Table` updates.
3. **Edit Time:** User double-clicks "Time" column in `Table` -> Types new time -> Row re-sorts automatically.
4. **Jump:** User clicks row in `Table` -> Video player jumps to that timestamp.
