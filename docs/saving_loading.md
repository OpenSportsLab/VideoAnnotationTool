# Saving And Loading

## Loading

Use **File > Load Dataset** (`Ctrl+O`) to open an OSL JSON file.

The app normalizes loaded content (for example, missing IDs) while preserving unknown root/sample fields when possible.

## Saving

- **Save Dataset** (`Ctrl+S`): writes to current path.
- **Save Dataset As** (`Ctrl+Shift+S`): writes to a new path.

On write, paths in `data[].inputs[].path` are rewritten relative to the chosen save location.

## Close With Unsaved Changes

If the dataset is dirty and you close/quit, the app prompts:

- **Save**
- **Save As**
- **Close Without Saving**
- **Cancel**

## What Is Persisted

- Core OSL fields (`labels`, `events`, `captions`, `dense_captions`, `questions`, `answers`)
- Unknown/custom root/sample fields

### Not persisted in dataset JSON

- Localization `label_colors` (stored in app settings)
