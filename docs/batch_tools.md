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

It supports JSON split downloads (`<split>.json`) and Parquet/WebDataset split
downloads (`<split>/`). Files are written under
`<output directory>/<revision>/<split>`. JSON-only mode fetches just the native
JSON, or reconstructs it from Parquet metadata without downloading media
shards. Dry run is disabled while JSON-only mode is selected.

After submission, downloads run in the background and the main annotation
workflow remains interactive. A compact status-bar widget shows the current
stage. While a file is transferring, it shows the filename and transferred
size over its total size (for example, `384.0 MB / 2.0 GB`) together with a
determinate progress bar. Operations for which Hugging Face does not provide a
byte total remain animated. Its **Cancel** button requests cancellation without
opening a blocking progress dialog. Only one full or selective dataset download
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
