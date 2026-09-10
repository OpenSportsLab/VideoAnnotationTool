# Troubleshooting

## App Fails to Start

- Confirm your environment is active.
- Reinstall dependencies:

```bash
pip install -r requirements.txt
```

## Dataset JSON Does Not Load

- Confirm the file is valid JSON.
- Confirm the root value is a JSON object, not an array.
- Confirm top-level `data` is a list.
- Check the expected structure in [OSL JSON Format](OSL.md).

Legacy VQA files that use top-level `questions` and per-answer `question_id`
entries should be converted before editing:

```bash
python tools/convert_legacy_vqa_to_grouped.py \
  --input-json old_vqa.json \
  --output-json grouped_vqa.json
```

## Large Dataset Is Still Populating

Datasets with thousands of samples keep the left explorer bounded to the page
size configured under **Edit → Settings… → Dataset Explorer** (500 by default).
The range below the tree shows which samples are visible. Scroll down again at
the bottom for the next page or up at the top for the previous page. The bottom
page field and arrow buttons also support direct navigation. Filtering rebuilds
pages from all matching samples; it does not discard data. The JSON
inspector and classification batch-range lists are intentionally prepared only
when opened so they do not delay project loading. An active sample can continue
playing while its row is off-page.

## Media Files Are Missing After Loading

Relative paths in `data[].inputs[].path` are resolved from the directory that
contains the dataset JSON. If the JSON was moved separately from its media
folders, move the folders back beside the JSON or update the paths.

For a Hugging Face-sourced metadata-only dataset, **Input not downloaded** is
expected for any absent video, NumPy frame stack, tracking Parquet, or player H5
input. Right-click its input or parent sample in the Dataset Explorer to download
it. The pane says **Input download in progress** while that requested file is
transferring. Unsupported-format/schema messages are reserved for files that
exist locally but cannot be handled by their declared input type.

!!! tip "Saving can repair path layout"
    After opening a dataset from the intended folder, **Save Dataset As** can
    rewrite input paths relative to the new JSON location.

## Hugging Face Transfer Errors

- Ensure `huggingface_hub` is installed.
- Authenticate if dataset access is gated:

```bash
huggingface-cli login
```

- For upload failures:
  - `Repository Not Found`: create the repo or let the app create it from the prompt.
  - `Revision/Branch Not Found`: create the branch or let the app create it from the prompt.
  - Xet timeout on a large file: retry from **Data → Upload Dataset to HF**
    with **Use Xet for this upload** unchecked. Xet remains enabled by
    default because it normally provides faster transfers.
- If an Xet-backed download itself fails or times out, retry with **Use Xet for
  this download** unchecked. Download and upload choices are stored separately
  and apply only to their respective transfer.
- If **Download dataset JSON only** is unavailable, the active OpenSportsLib
  installation does not expose the selective-download API. Full dataset
  downloads still work; install the local feature version to enable it.
- If a dataset explorer download action asks you to re-download the dataset,
  its JSON has legacy provenance without `hf_format` or `hf_commit`. Download
  the split again so assets can be pinned to the same immutable commit.
- Selective-download summaries distinguish requested files from collateral
  files extracted from the same shard. Existing collateral is intentionally
  skipped and is never affected by the overwrite choice.
- Active downloads open the **Transfers** dock below Dataset Explorer. It keeps
  overall stage/count progress separate from the current file's downloaded
  size and byte progress. The default **File progress** mode has the least
  bookkeeping overhead. **Byte progress** can run with Xet and reports exact
  transferred sizes, though repository files are handled individually rather
  than through a concurrent snapshot operation. Older
  OpenSportsLib versions retain background downloads but show only stage/count
  progress. Use **Cancel** in the dock to stop at the next safe cancellation
  point. The dock hides when the transfer ends; reopen it from **View →
  Transfers** to inspect or clear the latest summary.
- Sample/input download actions are greyed out while a dataset download is
  active because full and selective downloads share one worker slot. If you
  attempt to quit, choose **Keep App Open** to finish the transfer or **Stop
  Download and Quit** to cancel it and close the application.
- Parquet upload stops before conversion if any primary input or `ball_path` is
  missing. For datasets with complete `hf_repo_id`, `hf_split`, `hf_format`, and
  `hf_commit` provenance, choose **Download Missing Files** to hydrate and
  revalidate automatically. Without pinned provenance, restore the listed files
  manually; the app will not upload incomplete shards.

## Download URL 404 / Not Found

- Verify the repo ID, revision, split, and format in the dialog.
- JSON mode expects `<split>.json`.
- A JSON upload can be made from a partially downloaded dataset. Missing local
  input references are skipped without failing the upload, and existing remote
  files at those paths remain unchanged. Parquet + WebDataset upload still
  requires every referenced input locally so that complete shards can be built.
- Parquet mode expects a `<split>/` folder.
- If a previously successful URL is now invalid, reselect or correct it in the
  dialog.

## Video Playback Error or Black Screen

Some codecs are not decoded by your platform backend. Convert to H.264/AAC MP4:

```bash
ffmpeg -i input.mp4 -vcodec libx264 -acodec aac output.mp4
```

## No Playback After Selecting a Row

If the selected input is not playable media for the current backend, the row can
stay selected while playback does not start. For example, `frames_npy` and
`tracking_parquet` inputs use specialized renderers, and unsupported text or
metadata files are not played as video. `player_joints_h5` and
`player_centroids_h5` inputs require a valid `timestamp_utc` column because
playback timing is derived from absolute UTC timestamps.
