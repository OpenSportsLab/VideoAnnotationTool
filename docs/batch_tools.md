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

It supports JSON split downloads (`<split>.json`) and Parquet split downloads
(`<split>/`). Files are written under `<output directory>/<revision>/<split>`.

For successful non-dry-run JSON downloads, source metadata is written into the
JSON root:

- `hf_repo_id`
- `hf_branch`
- `hf_split`

!!! note "Dry-run support"
    Dry-run size estimation is available for JSON downloads. Parquet downloads
    run as real downloads/conversions.

### Upload Dataset to HF...

Upload requires an opened dataset JSON from disk.

Upload modes:

- **Upload as JSON** uploads the current dataset JSON plus every file referenced
  by `data[].inputs[].path`.
- **Parquet + WebDataset** converts locally, then uploads generated
  Parquet/WebDataset artifacts.

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
