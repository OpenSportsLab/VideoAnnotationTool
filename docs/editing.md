# Editing

## Edit Sample IDs

- Double-click a top-level sample row in the Dataset Explorer tree to rename its `id`.
- IDs are kept unique (`__2`, `__3`, ...) when collisions occur.

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
- Q/A: edit answers per selected question.

## Remove Data

- Right-click a sample row: **Remove Sample**
- Right-click an input child row: **Remove Input**

If a sample loses its last input, the whole sample is removed.
