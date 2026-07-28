# Synchronized Multi-Modality Playback

When a sample contains two or more inputs, the Media Center displays all inputs
in a two-column grid and controls them with one shared timeline. Selecting an
input in the Dataset Explorer or clicking a viewer focuses that pane without
unloading the other modalities.

## Timeline Alignment

Inputs with an absolute origin are aligned by UTC:

- `UTC_time_start` on an input identifies the UTC instant at its local
  `00:00.000` position.
- For player-joints and player-centroids H5 inputs, the earliest valid
  `timestamp_utc` is used when `UTC_time_start` is absent.
- An explicit, valid `UTC_time_start` overrides an H5-derived origin.
- Inputs without UTC timing start at shared elapsed zero and are marked
  **Relative**.

The shared timeline spans the union of the UTC-aligned inputs. A viewer shows
**Not available at this UTC time** when the shared playhead is before its start
or after its end.

Accepted `UTC_time_start` values include a space or `T` date/time separator,
optional fractional seconds, `Z`, and explicit timezone offsets. Naive values
are interpreted as UTC. An invalid explicit value is shown as
**Relative ⚠ invalid UTC_time_start** and intentionally does not fall back to
internal H5 timing.

## Jump to a Modality Boundary

Right-click a playable viewer and choose:

- **Go to start** to move the shared playhead to that modality's first frame.
- **Go to end** to move the shared playhead to that modality's final frame.

For timestamped raster and H5 inputs, **Go to end** uses the last timestamped
frame. For video, it uses the media duration. All viewers follow the shared
seek and remain synchronized. These actions are disabled while synchronization
mode is active.

## Correct an Input's UTC Alignment

Use visual synchronization when one modality is early or late:

1. Seek the shared group to a frame that is easy to identify in another
   modality.
2. Right-click the modality that needs correction.
3. Choose **Synchronize this modality**.
4. The group pauses. The reference panes remain frozen at the current absolute
   UTC anchor.
5. Use Play/Pause, the timeline, relative seek controls, or **Frame Back** and
   **Frame Forward** to find the matching frame in the selected modality.
6. Check the proposed UTC start shown in the synchronization bar.
7. Choose **Apply**, or choose **Cancel** to discard the adjustment.

Synchronization requires at least two playable inputs and at least one valid
absolute UTC reference in the sample. During synchronization, normal playback
controls affect only the selected modality. Left and Right step by an exact H5
or raster timestamp; video stepping uses the input FPS, Qt metadata FPS, or a
25 FPS fallback.

The applied value is calculated as:

```text
UTC_time_start = frozen anchor UTC - selected local position
```

It is saved with six fractional digits. Apply and Cancel both leave the group
paused, and changing samples or projects cancels synchronization without saving.

## Existing Timed Annotations

Localization events and dense captions store `position_ms` relative to the
shared union start. If synchronization changes that start, the tool shifts both
annotation collections automatically:

```text
new position_ms = old position_ms + old union origin - new union origin
```

This preserves every annotation's absolute UTC instant. The `UTC_time_start`
change and all annotation shifts form one undoable edit. Applying a semantically
equivalent UTC value creates no history entry.

If annotations were changed by a version of the tool that predates this
correction, undo the old synchronization and apply it again when possible. A
saved-and-reopened project needs the previous UTC origin or a backup to recover
the original absolute annotation times.

## Audio

Audio-capable panes play together by default. Each pane has an independent mute
button. The global mute button temporarily mutes all feeds without losing their
individual mute settings.
