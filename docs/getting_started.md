# Getting Started

This walkthrough takes you from an empty project to a saved OSL JSON dataset.
For field-level JSON details, use [OSL JSON Format](OSL.md) as the canonical
reference.

## 1. Launch

Start the app from the repository root:

```bash
python annotation_tool/main.py
```

You will land on the **Welcome** screen.

## 2. Create or Open a Dataset

- Choose **Create New Dataset** to start with a blank OSL JSON project.
- Choose **Load Dataset** to open an existing `.json` file.
- Reopen known files from the recent-datasets list when available.

!!! warning "Keep JSON and media paths together"
    OSL input paths are usually relative to the dataset JSON file. If you move a
    JSON file without moving the referenced media folders, playback may fail
    until the paths are fixed or the dataset is saved again in the expected
    location.

## 3. Add Samples

In the Dataset Explorer:

1. Click **Add Data**.
2. Select one or more files, or select folders that contain supported files.
3. Review the sample rows that appear in the tree.

Selected files become separate samples. Selected folders are treated as
multi-input samples for multi-view workflows. The app stores each input under
`data[].inputs[]` and infers the input type from the file extension when needed.

## 4. Annotate

Select a sample in the Dataset Explorer, then use the right-side annotation tabs:

| Tab | Use it for | JSON field |
|---|---|---|
| `CLS` | Clip-level classification labels | `labels` |
| `LOC` | Timestamped events | `events` |
| `DESC` | Clip-level text captions | `captions` |
| `DENSE` | Timestamped dense captions | `dense_captions` |
| `Q/A` | Per-sample question groups and answers | `answers` |

See [Annotating](annotating.md) for the per-mode workflow.

## 5. Save

- **Save Dataset** (`Ctrl+S`) writes to the current JSON path.
- **Save Dataset As** (`Ctrl+Shift+S`) writes to a new JSON path.

On save, the app normalizes sample IDs, removes empty optional task blocks, and
rewrites `data[].inputs[].path` relative to the saved JSON location when
possible. See [Saving and Loading](saving_loading.md) for the full save behavior.

When you close with unsaved changes, choose **Save**, **Save As**,
**Close Without Saving**, or **Cancel**.
