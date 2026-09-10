# FAQ

## Which file types can I add as inputs?

The Add Data picker supports common video/image extensions (`.mp4`, `.avi`, `.mov`, `.mkv`, `.jpg`, `.jpeg`, `.png`, `.bmp`) plus `.npy`, `.parquet`, `.h5`, and `.hdf5` data inputs.

Video files use native video playback. `.npy`, `.parquet`, `player_joints_h5`,
and `player_centroids_h5` inputs use specialized raster preview renderers.

## Why did a sample ID change to `__2`?

When duplicate or missing IDs are loaded, the app normalizes them to unique IDs (for example `clip_dup`, `clip_dup__2`).

## Where are localization label colors stored?

In application settings (`QSettings`), not in the dataset JSON.

## Where are customized media controls stored?

Playback factors and relative-seek intervals from **Edit → Settings…** are
application-wide `QSettings` preferences. They are not saved in or exported
with dataset JSON.

Project, media, and Localization key bindings on the **Shortcuts** settings page
are also application-wide `QSettings` preferences. Quit, Undo, and Redo remain
platform-standard. Configurable bindings must be non-empty, distinct, and free
of prefix conflicts.

Localization event pre-roll is another application-wide preference. It defaults
to `0 ms`, is clamped between `0` and `60000 ms`, and affects only seeking to
events—not the values saved in `events[]`.

## Where is the Dataset Explorer page size stored?

The value from **Edit → Settings… → Dataset Explorer** is an application-wide
`QSettings` preference. It defaults to 500 and is not part of dataset JSON.

## Why is HF upload disabled?

Upload is available only when a dataset JSON is currently opened from disk (not unsaved in-memory only).

## Why does a recent dataset entry disappear?

If the file no longer exists, the app removes the stale entry from recents.

## Where do I report bugs?

Open an issue at:

- https://github.com/OpenSportsLab/VideoAnnotationTool/issues
