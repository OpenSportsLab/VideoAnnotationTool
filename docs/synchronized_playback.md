# Synchronized Multi-Modality Playback

When a sample contains two or more inputs, the Media Center displays all inputs
in a two-column grid and controls them with one shared timeline. Selecting an
input in the Dataset Explorer or clicking a viewer focuses that pane without
unloading the other modalities. If the sample is already active, selecting one
of its input rows changes only the highlighted viewer contour: it preserves the
current timestamp and does not start, stop, pause, or resume playback. This also
applies after seeking by selecting an annotation in Localization or Dense
Description: the annotation-table selection remains intact and is not emitted
again as a second seek.

Selecting the parent sample row clears every modality contour. It preserves the
current playback state: an already playing group keeps playing, while a paused
or stopped group remains that way. When the row belongs to another sample, the
new group is loaded with that same playing/paused state and with no focused
modality.

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

## Set, Correct, or Remove a UTC Start

Right-click a viewer to manage its explicit modality origin:

- Choose **Set UTC start…** when the input has no explicit `UTC_time_start`.
- Choose **Correct UTC start…** to replace an existing value; the dialog is
  prefilled with the current value.
- Choose **Remove UTC start** and confirm to remove only the explicit override.
  Timestamped backends such as H5 then resume using their backend-derived UTC.

The entered timestamp always describes that modality's local `00:00.000`, not
the frame currently displayed. Set, correct, and remove are each one undoable
edit. Invalid input is rejected without changing the project. After an
effective edit, the group is rerouted, remains paused, and preserves the
current absolute playback anchor when possible.

## Jump to a Modality Boundary

Right-click a playable viewer and choose:

- **Go to start** to move the shared playhead to that modality's first frame.
- **Go to end** to move the shared playhead to that modality's final frame.

For timestamped raster and H5 inputs, **Go to end** uses the last timestamped
frame. For video, it uses the media duration. All viewers follow the shared
seek and remain synchronized. These actions are disabled while synchronization
mode is active.

Timeline scrubbing, the ±1/5-second controls, and Localization/Dense annotation
navigation are explicit group seeks. They reposition the active video clock as
well as the other modalities, including while playback is running, so the
timeline does not snap back to the pre-seek position.

Raster panes render outside the UI thread during synchronized playback. If a
complex skeleton frame takes longer to draw than the source frame interval,
completed forward-progress frames remain visible while the renderer catches up
to the shared playhead; playback does not stay frozen on the first frame.

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

Localization events and dense captions may store an authoritative
`timestamp_utc` together with a compatibility `position_ms`. Before changing an
input origin, the tool promotes legacy relative annotations when the old sample
origin is genuinely resolvable. It then leaves every valid annotation UTC
unchanged and recomputes its projected position against the new union origin:

```text
position_ms = timestamp_utc - current sample timeline origin
```

This means adding or removing the earliest modality, filtering inputs at read
time, or correcting synchronization changes only the derived timeline
positions. Absolute annotations outside the currently available media range
are preserved and may project to a negative or beyond-duration position. The
input-origin update and compatibility-field recomputation form one undoable
edit; a semantically equivalent value creates no history entry.

Legacy annotations remain relative when no genuine UTC origin exists. A
malformed `timestamp_utc` is preserved and the UI falls back to `position_ms`;
it is replaced only when that annotation is explicitly edited.

## Audio

Audio-capable panes play together by default. Each pane has an independent mute
button. The global mute button temporarily mutes all feeds without losing their
individual mute settings.
