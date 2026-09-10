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
- dry-run mode
- **Download dataset JSON only (no media)**, off by default
- **Use Xet for this download**, on by default for faster transfers; uncheck it
  only as a fallback when an Xet-backed download fails or times out
- **Progress detail**: **File progress** has the least overhead and is the
  default; **Byte progress** reports exact transferred sizes and also supports
  Xet

It supports JSON split downloads (`<split>.json`) and Parquet/WebDataset split
downloads (`<split>/`). Files are written under
`<output directory>/<revision>/<split>`. JSON-only mode fetches just the native
JSON, or reconstructs it from Parquet metadata without downloading media
shards. Dry run is disabled while JSON-only mode is selected.

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

**Use Xet** and **Byte progress** can be selected together. OpenSportsLib adapts
Xet's native byte updates to the application progress bar. With Xet disabled,
the same mode obtains byte updates from the classic HTTP fallback.

After submission, downloads run in the background and the main annotation
workflow remains interactive. The **Transfers** dock opens below Dataset
Explorer and shows both the current stage/item count and the current
repository-relative filename with its transferred size (for example,
`384.0 MB / 2.0 GB`) in Byte-progress mode. These are separate progress bars,
so file-byte progress does not replace overall progress. File-progress mode has
less bookkeeping overhead and may use concurrent snapshot downloads, while
Byte-progress mode downloads repository files individually so it can report
each file's transferred bytes; Xet acceleration remains active within those
downloads. Its **Cancel** button requests
cancellation without opening a blocking progress dialog. The dock hides after a
terminal transfer and can be reopened from **View → Transfers** to inspect the
latest session summary or clear it. Only one full or selective dataset download
can run at a time.

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

While any full or selective dataset download is running, both explorer download
actions remain visible but are disabled. They become available again when the
active download completes, fails, or is cancelled.

If requested files already exist, one prompt offers **Replace Existing**,
**Keep Existing**, or **Cancel**. Replace applies only to the explicitly
requested files; other files found while unpacking a Parquet/WebDataset shard
are written only when missing. A required shard is downloaded once, all missing
safely mapped assets in it are extracted opportunistically, and the temporary
shard is removed. The completion message reports requested, opportunistic,
overwritten, skipped, missing, and failed counts.

If you close the application while a dataset download is active, a warning
offers **Keep App Open** to let it finish or **Stop Download and Quit**. Keeping
the app open does not interrupt the transfer.

Selective actions require all five Hugging Face provenance fields. Older
datasets that lack `hf_format` or `hf_commit` must be downloaded again. With an
older OpenSportsLib installation, normal full downloads remain available while
the JSON-only checkbox and selective actions explain that a newer local library
is required.

Completing a dataset later with a full download is supported even when the
JSON-only download already created `<split>.json`.

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
