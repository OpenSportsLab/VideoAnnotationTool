# 🏷️ Classification Controllers

This module contains the business logic specifically designed for the **Whole-Video Classification** task.

In this mode, the goal is to assign global attributes (labels) to an entire video clip (e.g., "Weather: Sunny", "Action: Goal"). With the latest updates, these controllers now bridge the gap between the Classification UI, the central data model (`models.py`), and the **AI-powered `soccernetpro` framework** for smart inference and model training.

## 📂 Module Contents

```text
controllers/classification/
├── class_annotation_manager.py # Labeling logic, Dynamic Schema & Smart Annotations
├── class_file_manager.py       # I/O operations (Save/Load/Create + Smart Labels)
├── class_navigation_manager.py # Video list navigation, Filtering & Playback flow
├── inference_manager.py        # [NEW] AI Inference (Single & Batch Prediction)
└── train_manager.py            # [NEW] AI Model Training & Checkpoint logic
```

---

## 📝 File Descriptions

### 1. `class_annotation_manager.py`
**Responsibility:** Manages the labeling process, schema modifications, and AI prediction confirmations.

* **Manual Annotation Management**: Captures the user's selection from the UI (Right Panel), validates it, and commits it to the central State Model.
* **Smart Annotation Confirmation**: **[NEW]** Handles the logic for confirming AI-generated single and batch predictions, safely migrating them into the application's core memory.
* **Dynamic Schema Management**: Handles adding, renaming, or deleting Categories ("Heads") and Labels directly from the UI.
* **Universal Undo/Redo Integration**: Pushes precise commands to the `HistoryManager` when annotations (manual or smart) are changed, or when the schema structure is modified.

### 2. `class_file_manager.py`
**Responsibility:** Handles file input/output, JSON parsing, and project lifecycles.

* **Project Creation**: Orchestrates the "New Project" wizard dialog and initializes the model with default or blank schemas.
* **Robust JSON Handling**: Parses and strictly validates existing Classification JSON files to ensure they match expected dataset structures.
* **Smart Label I/O**: **[NEW]** Seamlessly reads and exports `smart_labels` alongside traditional manual labels, preserving AI-generated confidence scores.
* **Relative Pathing**: Converts absolute file paths to relative paths during export to ensure project portability across different machines.

### 3. `class_navigation_manager.py`
**Responsibility:** Manages the dataset list (Left Panel), complex filtering, and playback synchronization.

* **Model/View Navigation**: Connects the custom `ProjectTreeModel` to the unified `MediaController`, ensuring robust, ghost-frame-free video loading when items are clicked.
* **Advanced 4-State Filtering**: **[NEW]** Implements sophisticated visibility logic to filter clips by status: *Show All*, *Hand Labelled*, *Smart Labelled*, or *No Labelled*.
* **Smart Navigation**: Implements logic for "Next Action" (jump to next parent item) and "Next Clip" (jump to next child view), automatically skipping hidden items based on the active filter.

### 4. `inference_manager.py` (⭐ NEW)
**Responsibility:** Orchestrates AI-powered video predictions via the `soccernetpro` inference engine.

* **Dynamic Configurations**: Parses `config.yaml` on-the-fly to automatically map AI output indices to human-readable UI labels (eliminating hardcoded sports classes).
* **Asynchronous Execution**: Uses `QThread` workers (`InferenceWorker` and `BatchInferenceWorker`) to run heavy PyTorch inference without freezing the UI.
* **Single & Batch Processing**: Allows users to infer the current active video or run sweeping batch predictions across a specified range of clips.
* **Temporary Workspaces**: Safely handles the creation and cleanup of isolated hidden workspaces (`~/.soccernet_workspace`) to prevent pipeline conflicts.

### 5. `train_manager.py` (⭐ NEW)
**Responsibility:** Handles the background training loop for fine-tuning models on user-annotated data.

* **Hyperparameter Injection**: Collects variables (Epochs, LR, Batch Size, Device, Workers) from the UI and forcefully injects them into a runtime YAML configuration.
* **Background Training**: Executes the `myModel.train()` process inside a background `QThread` to ensure the application remains responsive.
* **Console Log Interception**: Uses a custom `io.TextIOBase` stream to intercept PyTorch stdout/stderr, parsing progress steps to drive the UI progress bar and displaying human-readable logs in the application console.
* **Checkpointing**: Auto-saves model weights into a dynamically generated `checkpoints/` directory alongside the dataset.
```
