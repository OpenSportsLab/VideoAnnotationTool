# Getting Started

## 1. Launch

Start the app from the repository root:

```bash
python annotation_tool/main.py
```

You will land on the **Welcome** screen.

## 2. Create Or Open A Dataset

- **Create New Dataset** for a blank OSL dataset.
- **Load Dataset** to open an existing JSON.
- You can also reopen files from the recent-datasets list.

## 3. Add Samples

In the Dataset Explorer:

- Click **Add Data**.
- Select files or folders.
- Selected folders are treated as multi-input samples (for multi-view workflows).

## 4. Annotate

Use the right-side tabs:

- `CLS` for classification labels
- `LOC` for timestamped events
- `DESC` for clip-level captions
- `DENSE` for timestamped dense captions
- `Q/A` for question bank + per-sample answers

## 5. Save

- `Ctrl+S` saves to the current JSON path.
- `Ctrl+Shift+S` saves as a new JSON file.

When you close with unsaved changes, you can **Save**, **Save As**, **Close Without Saving**, or **Cancel**.
