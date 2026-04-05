# Classification Event Editor

**Path:** `ui/classification/widgets/event_editor/`

## Overview

The **Event Editor** package is responsible for the **Right Panel** of the Classification Mode. It serves as the primary interface for manual data annotation. unlike the Localization mode which deals with timestamps, this editor focuses on assigning global attributes (labels) to entire video clips or actions.

It features a **schema-driven UI**, meaning the widgets (Radio Buttons or Checkboxes) are dynamically rendered based on the loaded project JSON configuration.

## Key Features

* **Dynamic Rendering:** Automatically generates UI groups based on the label definition (Schema).
* **Schema Management:** Allows users to add new Categories (Heads) and Labels dynamically during runtime.
* **Annotation Input:**
    * **Single-choice:** Uses Radio Button groups.
    * **Multi-choice:** Uses Checkbox groups.
* **Task Information:** Displays the current task name.
* **History Control:** Hosts the Undo/Redo buttons for the classification workflow.

## File Structure

```text
event_editor/
├── __init__.py           # Package entry point; exports the main classes.
├── editor.py             # Defines the main container widget (ClassificationEventEditor).
└── dynamic_widgets.py    # Defines the atomic UI components (Label Groups).

```

## Module Descriptions

### 1. `editor.py`

Contains the `ClassificationEventEditor` class (formerly `ClassRightPanel`).

**Responsibilities:**

* Layout management (Vertical layout).
* **Top Section:** Undo/Redo controls.
* **Info Section:** Task name display.
* **Schema Editor:** Input field and button to add new Label Heads.
* **Scroll Area:** Holds the dynamic list of label groups.
* **Bottom Section:** "Save Annotation" and "Clear Selection" buttons.

**Key Signals:**

* `add_head_clicked(str)`: Emitted when the user wants to add a new category.
* `remove_head_clicked(str)`: Emitted when a category is deleted.

### 2. `dynamic_widgets.py`

Contains the reusable widgets that represent a single Label Head (Category).

* **`DynamicSingleLabelGroup`**:
* Used when the schema type is `single_label`.
* Renders a `QButtonGroup` with `QRadioButton`s.
* Allows adding/removing individual labels within the group.


* **`DynamicMultiLabelGroup`**:
* Used when the schema type is `multi_label`.
* Renders a list of `QCheckBox`es.
* Allows multiple selections simultaneously.



### 3. `__init__.py`

Exposes the classes to the rest of the application.

```python
from .editor import ClassificationEventEditor
from .dynamic_widgets import DynamicSingleLabelGroup, DynamicMultiLabelGroup

```

## Usage Example

This module is typically instantiated within the `MainWorkspace` dockable layout.

```python
# In ui/common/workspace.py
from ui.classification.widgets.event_editor import ClassificationEventEditor

self.right_panel = ClassificationEventEditor()

# To populate the UI based on JSON schema:
self.right_panel.setup_dynamic_labels(label_definitions_dict)

# To get the user's current selection:
user_data = self.right_panel.get_annotation()

```

## Dependencies

* **PyQt6**: Core UI framework.
* **utils**: Uses `get_square_remove_btn_style` for the delete buttons.

