# Controllers Module

This package contains the application logic layer.

## Structure

```text
controllers/
├── __init__.py
├── dataset_explorer_controller.py
├── welcome_controller.py
├── router.py
├── media_controller.py
├── history_manager.py
├── classification/
│   ├── __init__.py
│   ├── classification_editor_controller.py
│   ├── inference_manager.py
│   └── train_manager.py
├── localization/
│   ├── __init__.py
│   ├── localization_editor_controller.py
│   └── loc_inference.py
├── description/
│   ├── __init__.py
│   └── desc_editor_controller.py
└── dense_description/
    ├── __init__.py
    └── dense_editor_controller.py
```

## Import Style

Use package-level imports for mode controllers:

```python
from controllers.classification import ClassificationEditorController
from controllers.localization import LocalizationEditorController
from controllers.description import DescEditorController
from controllers.dense_description import DenseEditorController
```

Shared controllers now live directly under `controllers/`:

```python
from controllers.dataset_explorer_controller import DatasetExplorerController
from controllers.welcome_controller import WelcomeController
```

## Notes

- `DatasetExplorerController` owns sample lifecycle flows (`add/remove/filter/clear`),
  Data-ID selection dispatch, and media routing.
- Mode controllers consume Data-ID selection and own mode-specific annotation/editor behavior.
- `DatasetExplorerController` also owns create/load/save/export lifecycle flows.
