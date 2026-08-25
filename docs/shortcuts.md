# Keyboard Shortcuts

## Project

- `Ctrl+O`: Load dataset JSON
- `Ctrl+S`: Save dataset
- `Ctrl+Shift+S`: Save dataset as
- `Ctrl+D`: Open HF download dialog
- `Ctrl+U`: Open HF upload dialog
- `Ctrl/Cmd+Q`: Quit

## Undo/Redo

- `Ctrl/Cmd+Z`: Undo
- `Ctrl/Cmd+Shift+Z` or platform redo key: Redo

Undo and redo use the platform-standard shortcuts shown in the **Edit** menu.
Their availability follows the current undo and redo history.

## Media

- `Space`: Play/Pause
- `Left`: Seek backward ~40 ms
- `Right`: Seek forward ~40 ms
- `Ctrl+Left` / `Ctrl+Right`: Seek by the smallest interval configured under
  **Edit → Settings… → Media Controls** (1 second by default)
- `Ctrl+Shift+Left` / `Ctrl+Shift+Right`: Seek by the second-smallest configured
  interval (5 seconds by default); disabled when only one interval is configured

During modality synchronization, the same controls affect only the selected
modality. Left and Right step to the previous or next exact raster/H5 timestamp;
video inputs use their FPS (falling back to 25 FPS).
