# Editing

## Edit Sample IDs

- Double-click a top-level sample row in the Dataset Explorer tree to rename its `id`.
- IDs are kept unique (`__2`, `__3`, ...) when collisions occur.
- For Parquet/shard datasets, all sample IDs are read-only while any referenced
  media file is missing, including an input's `ball_path` companion. Hover over
  a sample to see why renaming is unavailable. Download the missing media with
  **Queue missing samples**; renaming becomes available when all referenced
  files are local. This preserves the IDs needed to retrieve files from shards.
- Local datasets and Hugging Face JSON datasets keep their normal rename behavior.

## Edit Header Fields

In the Dataset Explorer header table:

- Editable known fields: `version`, `date`, `dataset_name`, `description`, `metadata`
- Unknown/custom root keys are shown read-only
- Raw JSON tab reflects current in-memory state

## Edit Annotations

- Classification: change selected labels in head tabs.
- Localization: edit event time/head/label directly in the table.
- Description: edit caption text.
- Dense: edit event text/time in the table.
- Q/A: add question groups with a dialog, choose prior questions there or enter custom text, double-click or right-click to edit/remove groups, and use the **Answer** dialog plus answer-list right-click/double-click actions for answers.
- Streaming VQA: add/edit complete timestamped multiple-choice questions in a
  dialog, choose one correct option, and navigate with ask-time table rows.
  See [the workflow](annotating.md#streaming-vqa).

### Action Spotting Event Metadata

In Localization, right-click an event row and choose **Edit Metadata…**. The
window uses the same formatted JSON text editor as manifest metadata and edits
the event under the pointer, even if another row was selected.

Enter a JSON object (dictionary), such as
`{"team": "home", "player": {"id": 7}, "tags": ["reviewed"]}`, and click
**OK**. Nested objects, arrays, and other JSON values are allowed inside the
object. Invalid JSON, a top-level array/scalar/null, and non-finite
numbers are rejected; the text stays available for correction. **Cancel**
discards the dialog's edits.

Events without metadata start with `{}`. Accepting `{}` or leaving the editor
blank (including whitespace only) removes the event's `metadata` field. If the
field is already absent, it stays absent with no undo step. Effective changes
apply immediately in memory as one undoable edit. Use Save or Export to write
them to JSON. Unchanged values add no undo step.

Metadata is stored in `data[].events[].metadata`. Editing an unconfirmed
prediction's metadata preserves its confidence and model information and does
not confirm it. Metadata also survives later event edits and confirmation.
This editor currently covers action spotting events only.

## Add or Remove Data

- Right-click a sample row: **Add Input...** to attach one or more additional files (or folders of files) to that sample, or **Remove Sample**
- Right-click an input child row: **Remove Input**

If a sample loses its last input, the whole sample is removed.
