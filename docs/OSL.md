# OSL JSON Format

The OSL JSON format is a unified, extensible data structure designed to handle multi-task video understanding datasets (e.g., action classification, action spotting, and various forms of video captioning) within a single file. 

By unifying dataset annotations, the OSL format makes it easy to load complex, multi-modal, and multi-task datasets without writing custom parsers for every new task.

Below is a detailed breakdown of the format, followed by a comprehensive example.

---

## 1. Top-Level Structure

The root of the OSL JSON document contains metadata about the dataset, the shared taxonomy for labels, and the actual data items.

| Field | Type | Description | Required |
| :--- | :--- | :--- | :---: |
| `version` | String | The version of the OSL format used (e.g., `"1.0"`). | Yes |
| `date` | String | The ISO-8601 formatted date when this split/file was produced (e.g., `"2025-10-20"`). | Yes |
| `dataset_name` | String | The name of the dataset and the specific split (e.g., `"OSL-Football-UNIFIED (train)"`). | Yes |
| `metadata` | Object | Global, file-level metadata (e.g., `source`, `license`, `created_by`, `notes`). | No |
| `tasks` | Array[String] | An advisory list of task families included in this file (e.g., `["action_classification", "action_spotting", ...]`). | No |
| `labels` | Object | The shared global taxonomy defining the available classes and their properties. | Yes* |
| `data` | Array[Object] | The list of data items (video clips) and their associated annotations. | Yes |

*\* Required if the dataset involves classification or spotting tasks.*

---

## 2. Shared Taxonomy (`labels`)

The top-level `labels` object defines the taxonomy used across all data items for tasks like action classification and action spotting. It supports multi-head outputs (e.g., predicting an "action" and "attributes" simultaneously).

Each key in the `labels` object represents a specific "head" and defines:
* `type`: Either `"single_label"` (exactly one class per item/event) or `"multi_label"` (zero or more classes).
* `labels`: An array of strings representing the valid class names.

**Example:**
```json
"labels": {
  "action": {
    "type": "single_label",
    "labels": ["Pass", "Shot", "Header", "Foul"]
  },
  "attributes": {
    "type": "multi_label",
    "labels": ["Aerial", "SetPiece"]
  }
}

```

---

## 3. Data Items (`data`)

The `data` array contains individual objects, each representing a specific data instance (typically a video clip) and all its multi-task annotations.

### Item Properties

| Field | Type | Description | Required |
| --- | --- | --- | --- |
| `id` | String | A unique identifier for this data item. All task targets below apply to this ID. | Yes |
| `metadata` | Object | Item-level metadata (e.g., `competition`, `stage`, `home_team`). | No |
| `inputs` | Array[Object] | A list of typed inputs associated with this item (e.g., raw video, extracted features, poses). | Yes |

### 3.1 Inputs

The `inputs` array defines the multi-modal data sources for the item. Different input types require different fields. Time references in annotations (like spotting or dense captioning) are relative to the start of the primary video file specified here.

**Common Input Types:**

* **Video:** `{ "type": "video", "path": "path/to/vid.mp4", "fps": 25 }`
* **Features:** `{ "type": "features", "name": "I3D", "path": "...", "dim": 1024, "hop_ms": 160 }`
* **Poses:** `{ "type": "poses", "format": "COCO", "path": "..." }`

*(Note: If referencing an untrimmed video, you can specify `start_ms` and `end_ms` within the video input object to define a specific segment.)*

### 3.2 Task Annotations

An item can contain annotations for multiple tasks simultaneously. Only the fields relevant to the tasks present in the dataset need to be included.

#### Action Classification (`labels`)

Assigns classes to the entire video clip based on the shared taxonomy defined at the top level.

* For `"single_label"` heads, use the `"label"` key (String).
* For `"multi_label"` heads, use the `"labels"` key (Array of Strings).

```json
"labels": {
  "action": { "label": "Header" },
  "attributes": { "labels": ["Aerial"] }
}

```

#### Action Spotting (`events`)

Defines instantaneous events occurring at specific timestamps within the clip.

* `head`: The taxonomy head to use (from top-level `labels`).
* `label`: The class name.
* `position_ms`: The timestamp of the event in milliseconds (relative to the start of the clip).

```json
"events": [
  { "head": "action", "label": "Header", "position_ms": 2100 }
]

```

#### Video Captioning (`captions`)

Provides text descriptions for the entire video clip. Multiple languages are supported.

* `lang`: Language code (e.g., `"en"`, `"fr"`).
* `text`: The caption string.

```json
"captions": [
  { "lang": "en", "text": "A precise cross finds the striker..." }
]

```

#### Dense Video Captioning (`dense_captions`)

Provides text descriptions for specific temporal segments within the video clip.

* `start_ms`: Start time of the segment in milliseconds.
* `end_ms`: End time of the segment in milliseconds.
* `lang`: Language code.
* `text`: The caption string for that segment.

```json
"dense_captions": [
  { "start_ms": 1200, "end_ms": 2500, "lang": "en", "text": "The winger accelerates..." }
]

```

---

## 4. Full Example

Below is a complete example of an OSL JSON file demonstrating a single data item with multiple inputs and multi-task annotations.

```json
{
  "version": "1.0",
  "date": "2025-10-20",
  "dataset_name": "OSL-Football-UNIFIED (train)",
  
  "metadata": {
    "source": "World Cup Finals",
    "license": "CC-BY-NC-4.0",
    "created_by": "OSL",
    "notes": "Single item demonstrates multi-task targets on the same ID."
  },
  
  "tasks": ["action_classification", "action_spotting", "video_captioning", "dense_video_captioning"],
  
  "labels": {
    "action": {
      "type": "single_label",
      "labels": ["Pass", "Shot", "Header", "Foul"]
    },
    "attributes": {
      "type": "multi_label",
      "labels": ["Aerial", "SetPiece"]
    }
  },
  
  "data": [
    {
      "id": "M64_multi_000",
      
      "metadata": {
        "competition": "FIFA WC",
        "stage": "Final",
        "home_team": "Germany",
        "away_team": "Argentina"
      },
      
      "inputs": [
        { "type": "video", "path": "FWC2014/224p/M64_multi_000.mp4", "fps": 25 },
        { "type": "features", "name": "I3D", "path": "features/I3D/M64_multi_000.npy", "dim": 1024, "hop_ms": 160 },
        { "type": "poses", "format": "COCO", "path": "poses/M64_multi_000.json" },
        { "type": "gamestate", "path": "gamestate/M64_multi_000.json" }
      ],
      
      "labels": {
        "action":     { "label": "Header" },
        "attributes": { "labels": ["Aerial"] }
      },
      
      "events": [
        { "head": "action", "label": "Header", "position_ms": 2100 },
        { "head": "action", "label": "Pass",   "position_ms": 3850 }
      ],
      
      "captions": [
        { "lang": "en", "text": "A precise cross finds the striker, who directs a powerful header on target." },
        { "lang": "fr", "text": "Un centre précis trouve l’attaquant, qui place une tête puissante cadrée." }
      ],
      
      "dense_captions": [
        { "start_ms": 1200, "end_ms": 2500, "lang": "en", "text": "The winger accelerates down the flank and delivers a looping cross." },
        { "start_ms": 2600, "end_ms": 4200, "lang": "en", "text": "The striker rises above the defense and heads the ball toward goal." }
      ]
    }
  ]
}

```
