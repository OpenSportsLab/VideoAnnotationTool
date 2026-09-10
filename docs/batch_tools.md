# Data Transfer and Batch Tools

The app supports Hugging Face dataset transfer from the **Data** menu and
script/API workflows for batch conversion. Dataset JSON inputs follow the
[OSL JSON Format](OSL.md).

## In-App Data Menu

### Download Dataset from HF...

The download dialog asks for:

- repo ID
- branch/revision
- split
- format
- output directory
- optional token
- **Queue sample media**, on by default; after the JSON is ready, add all
  referenced media that is missing locally to the transfer queue
- **Use Xet (faster downloads)**, on by default; uncheck it
  only as a fallback when an Xet-backed download fails or times out

Downloads always report byte-level progress, including when Xet is enabled.

It supports JSON split downloads (`<split>.json`) and Parquet/WebDataset split
downloads (`<split>/`). Files are written under
`<output directory>/<revision>/<split>`. Every GUI download fetches or reconstructs
the dataset JSON first. When it is ready, a prompt offers **Open Dataset** and
**Not Now**. The download-time **Queue sample media** checkbox controls whether
the remaining media is queued at that point.

Xet is Hugging Face's accelerated transfer backend and is enabled by default
for faster transfers. Very large files (for example, over 20 GB) can sometimes
time out with Xet; retry through classic HTTP by unchecking the relevant
option. The download and upload
dialogs save independent **Use Xet** choices. Unchecking the upload option is
the recommended workaround for known Xet timeouts on very large uploads; when
an upload fails with a timeout while Xet is enabled, the app displays that advice.
Each choice applies only for the duration of that transfer, after which the
previous Hugging Face process setting is restored. A checked option explicitly
sets `HF_HUB_DISABLE_XET=0` during the transfer so Xet is used when available;
an unchecked option sets it to `1`.

OpenSportsLib adapts Xet's native byte updates to the application progress bar.
With Xet disabled, it obtains byte updates from the classic HTTP fallback.

The **Transfers** dock starts hidden and is also available from **View →
Transfers**. After submission, downloads run in the background, the main annotation
workflow remains interactive, and the dock opens below Dataset
Explorer and shows completed files out of the expected file count, current-file
byte progress and download speed, and a compact list with **Queued** or
**Completed** states. An active row shows its byte count without a redundant
“Running” label, while the third column shows its whole-transfer average speed.
Downloads process repository files individually so each file's transferred
bytes can be reported; Xet acceleration remains active within those downloads.
When no download is active, the dock remains visible with empty, determinate
progress bars and an empty table. The controller owns one FIFO; the dock is only
a view of that queue. **Stop download** cancels the current low-level transfer
and puts its item back at the front, preserving all rows; **Download** then runs
queued items one after another in list order. **Clear** removes completed and
queued items without interrupting a transfer already in progress. **Queue
missing samples** adds every absent input referenced by the open JSON. One low-level
download runs at a time.

Closing the current project hides the Transfers dock when it is idle. If a
download is still active, the dock remains visible on the welcome screen so its
progress and controls stay accessible.

The app asks whether to open each JSON as soon as it becomes usable. If **Queue
sample media** was checked in the download dialog, all missing referenced inputs are appended to
the application queue and shown as **Queued** before they run. That JSON is not
offered a second time when the transfer finishes. When the checkbox is cleared,
media paths are neither discovered for display nor added to the queue.
Missing inputs are enqueued as ordered per-input jobs, preserving their order in
the JSON and in the Transfers table. When a job starts, its first row immediately
leaves the Queued state before any lower row can become active. If an earlier
Parquet/WebDataset job extracts a later queued input opportunistically, that row
is marked **Completed** immediately instead of remaining **Queued**.

For successful non-dry-run JSON downloads, source metadata is written into the
JSON root:

- `hf_repo_id`
- `hf_branch`
- `hf_split`
- `hf_format`
- `hf_commit` (the immutable commit resolved from the selected branch)

!!! note "Dry-run support"
    Dry-run size estimation is available for JSON downloads. Parquet downloads
    run as real downloads/conversions.

### Download media from a metadata-only dataset

Open the downloaded JSON, then right-click a sample or input in the Dataset
Explorer:

- **Download Sample Inputs from Hugging Face…** requests every input in that
  sample.
- **Download Input from Hugging Face…** requests the selected input and its
  optional `ball_path` companion.

The media viewer identifies any absent Hugging Face input as not downloaded and
shows this right-click guidance in the pane. This applies to videos, NumPy frame
stacks, tracking Parquet, and player H5 inputs. After a selective request starts,
the same pane changes to **Input download in progress** until the transfer
finishes. A file that exists but cannot be handled by its declared input type is
reported as unsupported instead.

During a selective download, both explorer actions remain enabled. Additional
sample/input requests join a FIFO queue and start automatically after the active
request finishes. The Transfers dock shows how many requests are waiting and
keeps the file history across stop/resume and across the queue. A full dataset
download still disables selective actions.

After Clear, a newly requested sample is the only waiting item. If no transfer
is active, that request starts immediately without pressing **Download**.

If requested files already exist, one prompt offers **Replace Existing**,
**Keep Existing**, or **Cancel**. Replace applies only to the explicitly
requested files; other files found while unpacking a Parquet/WebDataset shard
are written only when missing. A required shard is downloaded once, all missing
safely mapped assets in it are extracted opportunistically, and the temporary
shard is removed. Successful selective-media completion is reported only in the
status bar; it does not open a dialog or add a summary to the Transfers dock.

If you close the application while a dataset download is active, a warning
offers **Keep App Open** to let it finish or **Stop Download and Quit**. Keeping
the app open does not interrupt the transfer.

Selective actions require all five Hugging Face provenance fields. Older
datasets that lack `hf_format` or `hf_commit` must be downloaded again. The
JSON-first workflow and selective actions require the newer local OpenSportsLib
transfer API.

Media can be completed later with **Queue missing samples** after opening the
downloaded `<split>.json`.

### Upload Dataset to HF...

Upload requires an opened dataset JSON from disk.

Upload modes:

- **Upload as JSON** uploads the current dataset JSON plus every referenced
  primary input and `ball_path` that is currently available locally. Missing
  files are skipped, and their count is shown when the upload completes. Files
  already stored remotely but absent locally are left untouched.
- **Parquet + WebDataset** converts locally, then uploads generated
  Parquet/WebDataset artifacts.
- **Use Xet for this upload** is checked by default. Uncheck it to retry through
  classic HTTP when Xet times out, typically on a very large file.

Before a Parquet upload, the app verifies every primary input and `ball_path`.
It never creates or uploads partial shards. If files are missing and the JSON
has complete Hugging Face provenance, choose **Download Missing Files** to
restore them from the recorded immutable commit. The download runs in the
background; after it finishes, the app validates the dataset again and starts
the upload only when no references remain missing. Otherwise the upload stays
blocked and reports the remaining paths.

Replacing an existing split also removes obsolete managed shard files in the
same atomic Hugging Face commit. Other files in the repository folder are not
removed. The completion dialog reports how many obsolete shards were deleted.

If the target repository or branch is missing, the app can prompt to create it
and retry.

## CLI Scripts

Run commands from the repository root.

### Download Referenced Files

```bash
python tools/download_osl_hf.py \
  --repo-id <org/repo> \
  --revision main \
  --split test \
  --format json \
  --output-dir <LOCAL_DIR> \
  --dry-run
```

### Upload Referenced Files

```bash
python tools/upload_dataset_to_hf.py \
  --repo-id <org/repo> \
  --json-path <local_dataset.json> \
  --split test \
  --revision main \
  --format json
```

### Convert JSON to Parquet + WebDataset

```bash
python tools/osl_json_to_parquet_webdataset.py \
  annotations.json \
  /path/to/media/root \
  /path/to/output_dataset
```

### Convert Parquet + WebDataset Back to JSON

```bash
python tools/parquet_webdataset_to_osl_json.py \
  /path/to/output_dataset \
  reconstructed.json
```

## Python Conversion API

```python
from opensportslib.tools import convert_json_to_parquet, convert_parquet_to_json

convert_json_to_parquet(json_path="annotations.json", media_root=".", output_dir="out_parquet")
convert_parquet_to_json(dataset_dir="out_parquet", output_json_path="reconstructed.json")
```

For full script options, run any tool with `--help`.
