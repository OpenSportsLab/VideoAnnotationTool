# OSL JSON Format (As Used By This App)

This page describes the OSL-style structure expected and produced by the current Video Annotation Tool.

## Top-Level Structure

Required/standard fields:

- `version` (string)
- `date` (string)
- `dataset_name` (string)
- `description` (string)
- `modalities` (array, usually `["video"]`)
- `metadata` (object)
- `labels` (object)
- `questions` (array)
- `data` (array)

Unknown root keys are preserved.

## Labels Schema (`labels`)

Each head is a key under `labels`:

```json
"labels": {
  "action": {
    "type": "single_label",
    "labels": ["pass", "shot"]
  },
  "attributes": {
    "type": "multi_label",
    "labels": ["left_foot", "header"]
  }
}
```

## Sample Structure (`data[]`)

Each sample typically contains:

- `id` (string)
- `inputs` (array of input objects, each usually has `type` + `path`)
- Optional task blocks:
  - `labels` (classification)
  - `events` (localization)
  - `captions` (description)
  - `dense_captions` (dense description)
  - `answers` (Q/A)
- Optional `metadata`
- Any additional custom keys are preserved.

### `inputs`

Example:

```json
"inputs": [
  {"type": "video", "path": "test/action_0/clip_0.mp4", "fps": 25.0}
]
```

Multi-view samples can include multiple input entries.

### Classification payload (`labels` per sample)

- single-label head: `{"label": "shot"}`
- multi-label head: `{"labels": ["header", "left_foot"]}`
- smart predictions may include `confidence_score`

### Localization payload (`events`)

```json
"events": [
  {"head": "action", "label": "pass", "position_ms": 1234}
]
```

Smart localization events may include `confidence_score`.

### Description payload (`captions`)

```json
"captions": [
  {"lang": "en", "text": "A short caption."}
]
```

### Dense payload (`dense_captions`)

The current dense editor uses point timestamps:

```json
"dense_captions": [
  {"position_ms": 4567, "lang": "en", "text": "Dense description."}
]
```

### Q/A payload (`questions` + `answers`)

Top-level bank:

```json
"questions": [
  {"id": "q1", "question": "How are you?"}
]
```

Per-sample sparse answers:

```json
"answers": [
  {"question_id": "q1", "answer": "I am fine."}
]
```

## Save-Time Behavior

On save/export, the app:

- ensures unique sample IDs
- normalizes/filters invalid or empty answer entries
- removes empty optional task blocks
- rewrites input paths relative to the output JSON location
- preserves unknown root/sample fields
