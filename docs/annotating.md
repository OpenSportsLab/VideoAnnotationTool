# Annotating

All annotation tabs work on the currently selected sample from the Dataset
Explorer. The JSON field names below match the canonical [OSL JSON Format](OSL.md)
page.

For samples with a UTC reference, localization events and dense captions use an
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

Events are stored in `events[]` with `head`, `label`, and `position_ms`. When the
sample has an absolute origin, they also contain an authoritative
`timestamp_utc`. The Time column displays `YYYY-MM-DD HH:MM:SS.mmm UTC` whenever
that instant can be resolved, and otherwise displays relative `MM:SS.mmm`.
Double-click a UTC Time cell to enter an ISO-compatible value, including `Z` or
a timezone offset; the app normalizes it to UTC and updates `position_ms` for
seeking. Inference displays transient confidence-bearing rows;
confirming a row keeps the event and removes only the confidence marker.

## Description

Use `DESC` for one clip-level caption.

1. Select a sample and open `DESC`.
2. Enter or edit the caption text.
3. Wait for autosave or save the project.

The text is stored in `captions[]`. Manual description edits currently write an
English caption entry with `lang` set to `en`.

**Run Inference…** discovers local or remote captioning models. A returned
caption remains unchanged while the candidate is reviewed; rejecting is non-mutating.

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
