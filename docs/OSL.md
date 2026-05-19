# OSL JSON Format

This page describes the OSL-style JSON files loaded, edited, and written by the
Video Annotation Tool.

An OSL JSON file is a single JSON object with dataset metadata, a label schema,
and a `data` array of samples. Each sample points to one or more media inputs and
can carry task-specific annotations.

## Minimal Valid File

This is the smallest practical shape for a dataset with one video sample:

```json
{
  "version": "2.0",
  "date": "2026-05-19",
  "dataset_name": "minimal-demo",
  "description": "",
  "modalities": ["video"],
  "metadata": {},
  "labels": {},
  "data": [
    {
      "id": "clip_0001",
      "inputs": [
        {
          "type": "video",
          "path": "clips/clip_0001.mp4"
        }
      ]
    }
  ]
}
```

!!! note "Relative paths"
    Relative `inputs[].path` values are resolved from the folder that contains
    the JSON file. If you move the JSON without moving its media folders,
    playback can fail.

## Common Mistakes

| Mistake | Result | Fix |
|---|---|---|
| Root JSON is an array | The app rejects the file. | Use one root object with a `data` array. |
| `data` is missing or not a list | The app rejects the file. | Set `data` to `[]` or a list of sample objects. |
| Using top-level `questions` for Q/A | Legacy question banks are dropped on save. | Store Q/A in each sample's grouped `answers[]`. |
| Dense captions use `start_ms`/`end_ms` only | The current dense editor expects point timestamps. | Use `dense_captions[].position_ms`. |
| Annotation head names do not match root `labels` | Controls may not show the expected labels. | Keep `data[].labels` keys and `events[].head` values aligned with root `labels`. |
| Relative media paths no longer point to files | Samples load but playback cannot find media. | Keep media beside the JSON or resave after correcting paths. |

## Top-Level Object

The smallest useful file is a JSON object with `data` as a list. When loading,
the app fills missing standard fields with defaults. When saving, it writes the
standard project fields back out.

| Field | Type | Notes |
|---|---|---|
| `version` | string | Current app default is `"2.0"`. |
| `date` | string | Usually an ISO date such as `"2026-05-19"`. |
| `dataset_name` | string | Human-readable project name. |
| `description` | string | Free-text dataset description. Empty string is allowed. |
| `modalities` | array | Input types present in the dataset, for example `["video"]`. The app recomputes this from sample inputs on save. |
| `metadata` | object | Dataset-level custom metadata. |
| `labels` | object | Label schema shared by classification and localization heads. |
| `data` | array | Sample list. This must be a list. |

Unknown root keys are preserved, except retired legacy keys documented below.

## Label Schema

The root `labels` object defines annotation heads. Each head name is a key, and
each definition should include:

- `type`: `single_label` or `multi_label`.
- `labels`: list of allowed label strings.

```json
{
  "labels": {
    "action": {
      "type": "single_label",
      "labels": ["pass", "shot", "foul"]
    },
    "attributes": {
      "type": "multi_label",
      "labels": ["left_foot", "header", "set_piece"]
    }
  }
}
```

Classification and localization annotations should reference these same head
names. For example, `data[].labels.action` and `data[].events[].head == "action"`
both point at the root `labels.action` schema.

## Sample Objects

Each entry in `data` is one sample.

| Field | Type | Notes |
|---|---|---|
| `id` | string | Stable sample ID. Missing or duplicate IDs are normalized on load/save. Duplicates receive suffixes such as `__2`. |
| `inputs` | array | Media or feature files for this sample. Multi-view samples use multiple input entries. |
| `metadata` | object | Optional sample-level metadata. Empty metadata is removed on save. |
| `labels` | object | Classification payload for this sample. |
| `events` | array | Timestamped localization events. |
| `captions` | array | Clip-level description captions. |
| `dense_captions` | array | Timestamped dense descriptions. |
| `answers` | array | Grouped question/answer annotations. |

Unknown sample keys are preserved.

## Input Objects

Each sample should include `inputs`, even if the sample has only one media file.

```json
{
  "inputs": [
    {
      "type": "video",
      "path": "clips/clip_0001.mp4",
      "fps": 25.0
    }
  ]
}
```

Supported input types:

| Type | Typical path | Notes |
|---|---|---|
| `video` | `clips/clip_0001.mp4` | Default when type is missing and the extension is not special. |
| `frames_npy` | `frames/clip_0001.npy` | Uses `fps` for playback timing. The legacy alias `frame_npy` is normalized to `frames_npy`. |
| `tracking_parquet` | `tracking/clip_0001.parquet` | Uses parquet timestamps when available. Optional `fps` is a fallback. |

Input paths can be relative or absolute when loading. On save, input paths are
rewritten relative to the saved JSON file location when possible.

Multi-view samples use more than one input:

```json
{
  "id": "play_0001",
  "inputs": [
    {"type": "video", "path": "wide/play_0001.mp4", "fps": 25.0},
    {"type": "video", "path": "close/play_0001.mp4", "fps": 25.0}
  ]
}
```

## Task Payloads

### Classification

Sample-level `labels` uses the same head names defined at the root.

```json
{
  "labels": {
    "action": {
      "label": "shot"
    },
    "attributes": {
      "labels": ["left_foot", "set_piece"]
    }
  }
}
```

For smart predictions, a head payload may include `confidence_score` as a float
from `0.0` to `1.0`:

```json
{
  "labels": {
    "action": {
      "label": "shot",
      "confidence_score": 0.91
    }
  }
}
```

Confirming a smart prediction removes only `confidence_score`; the chosen label
stays as the manual annotation.

### Localization

Localization annotations live in `events`. Each event is a point timestamp in
milliseconds.

```json
{
  "events": [
    {
      "head": "action",
      "label": "pass",
      "position_ms": 1240
    },
    {
      "head": "action",
      "label": "shot",
      "position_ms": 4320,
      "confidence_score": 0.84
    }
  ]
}
```

`head` should match a root label head. Smart localization predictions use the
same optional `confidence_score` convention as classification.

### Description

Description annotations live in `captions`. The app writes one English caption
for manual description edits, but additional caption fields are preserved.

```json
{
  "captions": [
    {
      "lang": "en",
      "text": "A player receives the pass and shoots from the edge of the box."
    }
  ]
}
```

### Dense Description

Dense description annotations live in `dense_captions`. The current dense editor
uses point timestamps in milliseconds.

```json
{
  "dense_captions": [
    {
      "position_ms": 1200,
      "lang": "en",
      "text": "The midfielder receives the ball."
    },
    {
      "position_ms": 4300,
      "lang": "en",
      "text": "The forward takes a shot."
    }
  ]
}
```

### Question/Answer

Q/A annotations live in grouped per-sample `answers`. Each group stores the
question text and one or more non-empty answers.

```json
{
  "answers": [
    {
      "question": "What happens after the pass?",
      "answers": ["The receiving player shoots."]
    }
  ]
}
```

Legacy top-level `questions` and per-answer `question_id` entries are not
persisted. Convert old VQA files with `tools/convert_legacy_vqa_to_grouped.py`.

## Complete Examples

### Classification JSON

```json
{
  "version": "2.0",
  "date": "2026-05-19",
  "dataset_name": "soccer-classification-demo",
  "description": "Clip-level action labels.",
  "modalities": ["video"],
  "metadata": {
    "sport": "soccer",
    "split": "train"
  },
  "labels": {
    "action": {
      "type": "single_label",
      "labels": ["pass", "shot", "foul"]
    },
    "attributes": {
      "type": "multi_label",
      "labels": ["left_foot", "header", "set_piece"]
    }
  },
  "data": [
    {
      "id": "clip_0001",
      "inputs": [
        {
          "type": "video",
          "path": "clips/clip_0001.mp4",
          "fps": 25.0
        }
      ],
      "labels": {
        "action": {
          "label": "shot"
        },
        "attributes": {
          "labels": ["left_foot"]
        }
      },
      "metadata": {
        "match_id": "match_01"
      }
    }
  ]
}
```

### Localization and Dense Description JSON

```json
{
  "version": "2.0",
  "date": "2026-05-19",
  "dataset_name": "soccer-timeline-demo",
  "description": "Timestamped events and dense captions.",
  "modalities": ["video"],
  "metadata": {},
  "labels": {
    "action": {
      "type": "single_label",
      "labels": ["pass", "shot", "save"]
    }
  },
  "data": [
    {
      "id": "attack_0001",
      "inputs": [
        {
          "type": "video",
          "path": "clips/attack_0001.mp4",
          "fps": 25.0
        }
      ],
      "events": [
        {
          "head": "action",
          "label": "pass",
          "position_ms": 1100
        },
        {
          "head": "action",
          "label": "shot",
          "position_ms": 3650
        }
      ],
      "captions": [
        {
          "lang": "en",
          "text": "A quick attack ends with a shot on goal."
        }
      ],
      "dense_captions": [
        {
          "position_ms": 1100,
          "lang": "en",
          "text": "The midfielder plays a forward pass."
        },
        {
          "position_ms": 3650,
          "lang": "en",
          "text": "The striker shoots from inside the area."
        }
      ]
    }
  ]
}
```

### Multi-Input Q/A JSON

```json
{
  "version": "2.0",
  "date": "2026-05-19",
  "dataset_name": "multi-view-qa-demo",
  "description": "Two synchronized views with question/answer labels.",
  "modalities": ["video"],
  "metadata": {
    "sport": "basketball"
  },
  "labels": {},
  "data": [
    {
      "id": "possession_0001",
      "inputs": [
        {
          "type": "video",
          "path": "broadcast/possession_0001.mp4",
          "fps": 30.0
        },
        {
          "type": "video",
          "path": "baseline/possession_0001.mp4",
          "fps": 30.0
        }
      ],
      "answers": [
        {
          "question": "Which team ends the possession?",
          "answers": ["The home team."]
        },
        {
          "question": "How does the possession end?",
          "answers": ["A made three-point shot."]
        }
      ]
    }
  ]
}
```

## Save-Time Behavior

On save/export, the app:

- Ensures unique sample IDs.
- Normalizes input types, including `frame_npy` to `frames_npy`.
- Rewrites input paths relative to the output JSON location when possible.
- Recomputes `modalities` from `data[].inputs[]`.
- Removes empty optional sample fields such as `labels`, `events`, `captions`,
  `dense_captions`, `answers`, and `metadata`.
- Normalizes Q/A answers to grouped `{"question": ..., "answers": [...]}` entries
  with non-empty text.
- Drops legacy top-level `questions` and `question_id` answer entries.
- Drops retired sample smart keys such as `smart_labels` and `smart_events`.
- Does not persist localization `label_colors`; label colors live in app
  settings.
- Preserves unknown root and sample fields where possible.
