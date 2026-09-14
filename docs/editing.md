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

## Add or Remove Data

- Right-click a sample row: **Add Input...** to attach one or more additional files (or folders of files) to that sample, or **Remove Sample**
- Right-click an input child row: **Remove Input**

If a sample loses its last input, the whole sample is removed.
