# 📍 Localization Controllers

This module contains the business logic specifically designed for the **Action Spotting (Localization)** task. It handles the "timestamp-based" annotation workflow, bridging the gap between the complex Localization UI, the central data model, and the new **AI-Powered Smart Spotting** engine.

## 📂 Module Contents

```text
controllers/localization/
├── loc_file_manager.py     # Data Persistence & Project Lifecycle
├── loc_inference.py        # [NEW] AI Action Spotting & Sub-clipping logic
└── localization_manager.py # User Interaction, Timeline Sync & Logic Orchestration
```

---

## 📝 File Descriptions

### 1. `loc_file_manager.py`
**Responsibility:** Data Persistence & Project Lifecycle.

This controller manages the loading, saving, and creation of localization project files (`.json`). It ensures data integrity and handles file path resolution.

* **Project Loading**: Validates the JSON schema (checking for `events` and `inputs` fields) before loading data into the `AppStateModel`.
* **Smart Label I/O**: **[NEW]** Seamlessly parses and exports `smart_localization_events`, preserving AI-generated `confidence` scores alongside manual annotations.
* **Path Resolution**: Implements smart path fallback mechanisms. If an absolute path to a video is missing (e.g., when moving projects between computers), it attempts to resolve the video path relative to the JSON file.
* **Exporting**: Converts the internal data model into the standardized JSON format required for the SoccerNet ecosystem.
* **Workspace Management**: Handles the deep-cleaning logic for the interface (resetting the player, timeline, smart UI, and tables) when closing or creating a project.

### 2. `loc_inference.py` (⭐ NEW)
**Responsibility:** Orchestrates AI-powered temporal action localization.

This controller manages the background threads (`QThread`) that run the heavy `opensportslib` AI models, ensuring the UI remains responsive during long processing tasks.

* **Dynamic Sub-clipping**: Uses FFmpeg to extract precise temporal segments (based on user-defined start/end times) to speed up inference and target specific video regions.
* **Hardware Adaptation**: Dynamically patches `loc_config.yaml` on-the-fly within temporary workspaces (e.g., automatically configuring CPU fallback for Mac M1/M2 compatibility without touching the user's base config).
* **Timestamp Compensation**: Automatically calculates and maps relative timestamps generated from the sub-clipped video back to absolute `position_ms` coordinates on the full video's timeline.

### 3. `localization_manager.py`
**Responsibility:** User Interaction & Logic Orchestration.

This is the central "brain" for the localization view. It connects the visual components (Player, Timeline, Tables) with the data model and the AI inference manager.

* **Media Synchronization**: **[NEW]** Now leverages the unified `MediaController` to eliminate "ghost frames" and ensure robust, stable video loading when jumping between clips.
* **Smart Spotting Lifecycle**: **[NEW]** Manages the dual-state flow of AI annotations. It separates "Unconfirmed" predictions from "Confirmed" events, rendering them with distinct timeline colors (Gold for pending, Sky Blue for confirmed/manual).
* **Event Spotting & Adjustment**: Captures timestamps from the media player to create events. It also features a new utility to instantly snap an existing event to the current player timestamp.
* **Dynamic Schema Handling**: Manages the logic for adding, removing, or renaming "Heads" (Categories) and Labels via the Tab interface.
* **Undo/Redo Integration**: Wraps user actions (adding/deleting events, confirming smart batches) into Command objects to support the global Undo/Redo history.

---

## 🔄 Workflow Diagrams

### Manual Spotting Flow
1.  **User Action**: User clicks "Goal" button at `00:15`.
2.  **`localization_manager.py`**: 
    * Gets current time `15000ms`.
    * Creates event object: `{'head': 'Action', 'label': 'Goal', 'position_ms': 15000}`.
    * Updates `AppStateModel` and triggers UI refresh.
3.  **UI Update**: 
    * `TimelineWidget` paints a blue marker at 15s.
    * `AnnotationTableWidget` inserts a new row.

### AI Smart Spotting Flow
1.  **User Action**: User sets a time range and clicks "Run Smart Inference".
2.  **`loc_inference.py`**:
    * Clips the video via FFmpeg and creates a temporary workspace.
    * Runs the PyTorch model in a background thread and compensates the output timestamps.
3.  **`localization_manager.py`**:
    * Receives predictions and pushes them to `temp_smart_events` (Unconfirmed state).
    * `TimelineWidget` paints gold markers.
4.  **Confirmation**: User reviews the predictions and clicks "Confirm All". Events are migrated to `smart_localization_events` and markers turn blue.
5.  **Save**: `loc_file_manager.py` writes the combined manual and smart events to disk.
