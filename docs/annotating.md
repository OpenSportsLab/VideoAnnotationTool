# Annotating

All annotation tabs work on the currently selected sample from the Dataset
Explorer. The JSON field names below match the canonical [OSL JSON Format](OSL.md)
page.

## Classification

Use `CLS` for clip-level labels.

1. Select a sample.
2. Open `CLS`.
3. Add or choose label heads and labels.
4. Select the label values for the current sample.

Effective manual changes are saved immediately into the sample's `labels`
object. Single-label heads write `{"label": "..."}` and multi-label heads write
`{"labels": [...]}`. Smart predictions add `confidence_score` until confirmed or
rejected.

## Localization

Use `LOC` for point events on the timeline.

1. Select a sample and open `LOC`.
2. Choose a label head and label.
3. Move the playhead to the event time.
4. Use the spotting controls to add the event.
5. Edit or delete rows in the event table when needed.

Events are stored in `events[]` with `head`, `label`, and `position_ms`.
Smart inference can add predicted rows with `confidence_score`; confirming a row
keeps the event and removes only the confidence marker.

## Description

Use `DESC` for one clip-level caption.

1. Select a sample and open `DESC`.
2. Enter or edit the caption text.
3. Wait for autosave or save the project.

The text is stored in `captions[]`. Manual description edits currently write an
English caption entry with `lang` set to `en`.

## Dense Description

Use `DENSE` for timestamped text descriptions.

1. Select a sample and open `DENSE`.
2. Move the playhead to the desired timestamp.
3. Click **Add New Description**.
4. Enter text in the modal.
5. Edit time or text from the table when needed.

Dense descriptions are stored in `dense_captions[]` with `position_ms`, `lang`,
and `text`. The table keeps rows ordered by timestamp.

## Question/Answer

Use `Q/A` for grouped questions and one or more answers per question.

1. Select a sample and open `Q/A`.
2. Click **Add** to create a question group.
3. Choose a previous dataset question or enter custom question text.
4. Click **Answer** to add answer text.
5. Double-click or right-click a question or answer to edit or remove it.

Answers are stored as grouped `answers[]` entries with `question` and
`answers[]`. The app does not write a top-level `questions` bank.
