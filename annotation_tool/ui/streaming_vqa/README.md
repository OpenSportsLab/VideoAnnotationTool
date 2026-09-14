# Streaming VQA UI

`StreamingVQAAnnotationPanel` presents a chronological question table,
read-only selected-question details, and Add/Edit/Delete/Go to Ask Time actions.
It emits `addRequested`, `editRequested`, `deleteRequested`,
`entrySelected(int)` (raw sample-array index), and `seekRequested` intents.

`set_rows` restores selection with signals blocked. `edit_entry` opens
`StreamingVQADialog` and returns a complete payload or `None` on cancellation.
Widgets never write project state.

The dialog contains editable time and question text plus an exclusive radio
group of choice rows. Four empty rows are supplied for new questions. Adding,
removing, or reordering rows preserves surviving choice IDs and extra fields.
Removing the selected correct choice leaves correctness unset. Errors appear
inline; Save closes the dialog only when shared validation passes. An unchanged
dialog returns the original payload without promoting legacy time fields.

Display uses UTC when resolvable, otherwise relative `MM:SS.mmm`. The UTC editor
retains six fractional digits to avoid precision loss on an unchanged save.
Imported malformed entries are flagged and remain editable/deletable. There
are no evidence widgets, draft-save actions, or inference review controls.
