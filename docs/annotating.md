# Annotating

All annotation tabs work on the currently selected sample from the Dataset
Explorer. The JSON field names below match the canonical [OSL JSON Format](OSL.md)
page.

For samples with a UTC reference, localization events, dense captions, and Streaming VQA questions use an
absolute `timestamp_utc` as their stable time. The accompanying `position_ms`
is projected onto the current shared media timeline for seeking and legacy
compatibility. Adding, removing, filtering, or resynchronizing modalities can
change that projected position without changing the annotation's UTC instant. See
[Synchronized Multi-Modality Playback](synchronized_playback.md).

## Classification

Use `CLS` for clip-level labels.

1. Select a sample.
2. Open `CLS`.
3. Add or choose label heads and labels.
4. Select the label values for the current sample.

Effective manual changes are saved immediately into the sample's `labels`
object. Single-label heads write `{"label": "..."}` and multi-label heads write
`{"labels": [...]}`. Model predictions remain transient until accepted and
rejected.

## Localization

Use `LOC` for point events on the timeline.

1. Select a sample and open `LOC`.
2. Choose a label head and label.
3. Move the playhead to the event time.
4. Use the spotting controls to add the event.
5. Edit or delete rows in the event table when needed.

Select **Statistics…** beside **Events List** to see localization counts for the
current video. The popup groups classes by head, includes defined classes with
zero events, and counts both confirmed events and unconfirmed smart predictions.
Annotations whose head or class is not in the current schema are also included.
Opening the popup does not change the project or add an undo-history entry.

Selecting an event seeks playback to its timestamp. To see context before the
action, set **Localization event pre-roll** under **Edit → Settings… → Media
Controls**; for example, `1000 ms` seeks to one second before the selected event.
The setting changes navigation only and never changes the stored event time.

With a row selected, **Set to Current Video Time** updates that event to the
playhead. Its default shortcut is `Ctrl+Return`, configurable on the **Shortcuts**
settings page. The edit is saved through the normal history path and supports
undo/redo.

Events are stored in `events[]` with `head`, `label`, and `position_ms`. When the
sample has an absolute origin, they also contain an authoritative
`timestamp_utc`. The Time column displays `YYYY-MM-DD HH:MM:SS.mmm UTC` whenever
that instant can be resolved, and otherwise displays relative `MM:SS.mmm`.
Double-click a UTC Time cell to enter an ISO-compatible value, including `Z` or
a timezone offset; the app normalizes it to UTC and updates `position_ms` for
seeking. Inference writes confidence-bearing events into the sample immediately
after the result is applied. Confirming a row keeps the event and removes only
the confidence marker; rejecting it deletes the event.

Every completed localization inference run opens one dialog showing the
distinct returned classes. Add the predictions to the head selected when the
run started, choose another existing task head, or create a new task head.
Exact matches for the chosen existing head are filled in; map other classes or
leave them on **Skip Prediction**. Creating a head places every returned class
in it and requires a unique name. **Cancel** leaves the project unchanged. All
applied events, plus a new head when selected, can be undone in one step.

## Description

Use `DESC` for one or more ordered clip-level captions.

1. Select a sample and open `DESC`.
2. Select a caption from the list, or click **Add Caption**.
3. Edit its optional variant, language, and caption text.
4. Wait for autosave or save the project. Use **Delete Caption** to remove the
   selected row.

Each row is stored in `captions[]`. New rows start with `lang` set to `en`.
Editing a row preserves its position and any optional fields not shown by the
editor. This supports variant sets such as `auto`, `clean`, and `refined`.

**Run Inference…** discovers local or remote captioning models. A returned
caption remains unchanged while the candidate is reviewed. Accepting appends it
to the caption list; rejecting is non-mutating.

## Dense Description

Use `DENSE` for timestamped text descriptions.

1. Select a sample and open `DENSE`.
2. Move the playhead to the desired timestamp.
3. Click **Add New Description**.
4. Enter text in the modal.
5. Edit time or text from the table when needed.

Dense descriptions are stored in `dense_captions[]` with `position_ms`, `lang`,
and `text`, plus `timestamp_utc` when an absolute origin is available. The Time
column follows the same UTC display and ISO-compatible editing rules as
Localization, while row selection and media seeking continue to use the
projected `position_ms`. Relative-only samples keep the existing relative-time
editor.

Dense inference appends smart rows. Select a predicted row to confirm it as a
manual description or reject it. Models may advertise time-range support.

## Question/Answer

Use `Q/A` for grouped questions and one or more answers per question.

1. Select a sample and open `Q/A`.
2. Click **Add** to create a question group.
3. Choose a previous dataset question or enter custom question text.
4. Click **Answer** to add answer text.
5. Double-click or right-click a question or answer to edit or remove it.

Answers are stored as grouped `answers[]` entries with `question` and
`answers[]`. The app does not write a top-level `questions` bank.

Select a question and use **Run Inference…** to run VQA. An unconfirmed
answer carries confidence/model metadata; confirming it converts it to the
normal answer string. See [Local and Remote Inference](inference.md).

## Streaming VQA

Use **Streaming VQA** for a multiple-choice question asked at time T about what
has happened earlier in the selected sample. The answer must use only footage
from sample start through T. The editor allows normal playback beyond T while
authoring; selecting a question does not install a playback cutoff.

1. Select a sample, open **Streaming VQA**, and seek to the desired ask time.
2. Click **+ Add Question**. Playback pauses and the dialog captures the current
   shared timeline position, including when an individual input is focused.
3. Enter a question and fill the choices. The dialog starts with four empty
   choices; add, remove, or reorder them with the adjacent controls.
4. Select exactly one correct choice using its radio button. At least two
   distinct, non-empty choices are required.
5. Adjust ask time if needed, using `MM:SS.mmm` or an ISO UTC timestamp.
6. Click **Save** to commit the complete question, or **Cancel** to discard the
   dialog. Playback remains paused. Save the dataset to write changes to disk.

Questions appear chronologically in the table with ask-time markers on the
timeline. Selecting a row or clicking **Go to Ask Time** seeks to that time.
The details show the choices and mark the correct answer. Use **Edit** or
double-click to edit; **Delete** removes the selected question. Each committed
add, edit, or deletion is one undoable action. Unchanged or cancelled dialogs
do not add history entries.

Removing the correct choice requires selecting a replacement before saving.
Incomplete questions cannot be saved as drafts. Imported invalid rows show a
warning and repair details; they remain in the file until explicitly repaired
or deleted. **Show Labelled** includes samples with at least one valid question.
If an edit causes the filter to hide the selected sample, selection clears.

There are no evidence controls. This task supports manual annotation only;
**Run Inference…** is disabled while its tab is active.
