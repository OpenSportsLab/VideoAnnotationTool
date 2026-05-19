# Saving and Loading

This page covers project file behavior. For the exact JSON structure, see
[OSL JSON Format](OSL.md).

## Loading

Use **File > Load Dataset** (`Ctrl+O`) to open an OSL JSON file.

On load, the app validates that the root is a JSON object and that top-level
`data` is a list. It also fills missing standard root fields, normalizes missing
or duplicate sample IDs, canonicalizes known input types, and preserves unknown
root/sample fields when possible.

!!! note "Relative input paths"
    Relative `data[].inputs[].path` values are resolved from the directory that
    contains the opened JSON file.

## Saving

- **Save Dataset** (`Ctrl+S`) writes to the current path.
- **Save Dataset As** (`Ctrl+Shift+S`) writes to a new path.

On write, paths in `data[].inputs[].path` are rewritten relative to the chosen
save location when possible.

Save/export also:

- Ensures sample IDs are unique.
- Recomputes `modalities` from sample inputs.
- Removes empty optional sample blocks such as `labels`, `events`, `captions`,
  `dense_captions`, `answers`, and `metadata`.
- Normalizes Q/A payloads to grouped `answers[]` entries with non-empty answer
  text.
- Removes retired smart keys such as `smart_labels` and `smart_events`.

## Close With Unsaved Changes

If the dataset is dirty and you close or quit, the app prompts:

- **Save**
- **Save As**
- **Close Without Saving**
- **Cancel**

## What Is Persisted

- Standard OSL fields such as `labels`, `events`, `captions`,
  `dense_captions`, and grouped `answers`.
- Unknown/custom root and sample fields when they do not conflict with retired
  fields.

### Not Persisted in Dataset JSON

- Legacy top-level `questions` and per-answer `question_id` entries.
- Localization `label_colors`, which are stored in app settings.
