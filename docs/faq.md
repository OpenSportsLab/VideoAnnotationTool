# FAQ

## Which file types can I add as inputs?

The Add Data picker supports common video/image extensions (`.mp4`, `.avi`, `.mov`, `.mkv`, `.jpg`, `.jpeg`, `.png`, `.bmp`) plus `.npy`, `.parquet`, `.h5`, and `.hdf5` data inputs.

Video files use native video playback. `.npy`, `.parquet`, and `player_joints_h5`
inputs use specialized raster preview renderers.

## Why did a sample ID change to `__2`?

When duplicate or missing IDs are loaded, the app normalizes them to unique IDs (for example `clip_dup`, `clip_dup__2`).

## Where are localization label colors stored?

In application settings (`QSettings`), not in the dataset JSON.

## Why is HF upload disabled?

Upload is available only when a dataset JSON is currently opened from disk (not unsaved in-memory only).

## Why does a recent dataset entry disappear?

If the file no longer exists, the app removes the stale entry from recents.

## Where do I report bugs?

Open an issue at:

- https://github.com/OpenSportsLab/VideoAnnotationTool/issues
