# GUI Overview

The workspace has three regions: Dataset Explorer (left), Media Center (middle), and Annotation Editor tabs (right).

## Welcome Screen

![Welcome Interface](assets/landing-page.png)

- **Create New Dataset**
- **Load Dataset**
- Recent datasets list
- Links to docs/tutorial and GitHub

## Workspace Layout

The **View** menu controls the workspace layout. **Dataset Explorer** and
**Annotation Editor** can be shown or hidden independently. Under **Viewer
Layout**, choose **Single Modality**, **Mosaic**, or **Modality Tabs**. These
choices are application preferences and are restored when the app restarts;
they are not written to dataset JSON.

### Left: Dataset Explorer

- Tree of samples (parent row) and inputs (child rows)
- Filter: `Show All`, `Show Labelled`, `Show Smart Labelled`, `Show Not Labelled`
- `Add Data`, `Prev`, `Next`, `Clear All`
- Context menu on tree rows for removing a sample or a single input
- Header inspector tabs:
  - Known header fields (editable)
  - Unknown/custom root keys (read-only)
  - Raw JSON preview

Large datasets appear progressively in correctly sorted batches so the window
continues to repaint and accept input. Filters restart that progressive view
using only matching samples; they never change or partially load the canonical
dataset. The raw JSON text is generated only when its inspector tab is opened.

Selecting a sample row preserves playback state: playing streams continue and
paused or stopped streams do not start. A sample row has no focused modality,
so all viewer contours are cleared. Selecting one of the active sample's input
rows only highlights its viewer and likewise leaves playback unchanged.

### Middle: Media Center

- **Single Modality** shows one input at a time; selecting an input row in the
  explorer switches the visible modality
- **Mosaic** shows all inputs in the existing adaptive two-column grid
- **Modality Tabs** keeps one tab per input so the visible modality can be
  selected from the media center
- Timeline + zoom
- Marker overlays (mode-dependent)
- Playback controls (seek/playback rate)
- Mute icon button (state persists via app settings)
- Per-viewer right-click actions for **Go to start**, **Go to end**, manual UTC
  start management, and visual UTC synchronization

See [Synchronized Multi-Modality Playback](synchronized_playback.md) for UTC
alignment rules and the synchronization workflow.

Changing the viewer layout only changes presentation. Hidden modalities remain
loaded and synchronized, so switching layouts or tabs does not restart playback
or move the shared timeline. During manual UTC synchronization, single and tab
layouts stay pinned to the modality being synchronized.

### Right: Annotation Tabs

#### Classification (`CLS`)

![Classification Interface](assets/classification-UI.png)

- Edit label heads and labels
- Supports single-label and multi-label heads
- Manual edits are saved immediately on effective change
- Smart inference per head with confirm/reject

#### Localization (`LOC`)

![Localization Interface](assets/localization-UI.png)

- Spot events at current playhead time
- Head/label add/rename/delete + per-label colors
- Event table supports edit, delete, confirm/reject smart events
- Time shows full UTC when resolvable and relative time otherwise; media seeking
  still uses the projected timeline position
- Smart inference with model + time-range prompts

#### Description (`DESC`)

![Description Interface](assets/description-UI.png)

- Clip-level text editor for captions
- Autosaves after short idle delay when text changes

#### Dense Description (`DENSE`)

![Dense Description Interface](assets/dense-description-UI.png)

- `Add New Description` opens a modal and inserts at current playhead time
- Dense events are editable/deletable in the table
- Time shows full UTC when resolvable and accepts ISO-compatible UTC edits
- Events remain navigable by their projected `position_ms`

#### Question/Answer (`Q/A`)

![Question/Answer Interface](assets/question-answer-UI.png)

- Per-sample question groups
- `Add` opens a question-entry dialog with previous dataset questions and custom text entry
- Double-click or right-click a question group to edit it; right-click can also remove it
- `Answer` opens a multiline answer dialog
- Double-click or right-click an answer to edit it; right-click can also remove it
- Multiple answers per question
- Edits autosave after short idle delay
