# Batch Tools

The app supports Hugging Face dataset transfer from the **Data** menu and script/API workflows for batch conversion.

## In-App Data Menu

### Download Dataset from HF...

- Opens a dialog for:
  - HF URL
  - output directory
  - optional token
  - dry-run mode
- Supports:
  - JSON file URLs (`.../blob/.../annotations.json`)
  - Parquet folder URLs (`.../tree/.../<folder>`)
- On successful non-dry-run JSON download, source metadata is written into the JSON root:
  - `hf_source_url`
  - `hf_repo_id`
  - `hf_branch`

### Upload Dataset to HF...

Requires an opened dataset JSON from disk.

Upload modes:

- **Upload as JSON**: uploads current dataset JSON plus files referenced by `data[].inputs[].path` in one commit.
- **Parquet + WebDataset**: converts locally, then uploads generated Parquet/shards (shard size configurable).

If repository/branch is missing, the app can prompt to create it and retry.

## CLI Scripts

### Download referenced files

```bash
python test_data/download_osl_hf.py \
  --url <HF_JSON_OR_FOLDER_URL> \
  --output-dir <LOCAL_DIR> \
  --types video \
  --dry-run
```

### Upload referenced files

```bash
python test_data/upload_osl_hf.py \
  --repo-id <org/repo> \
  --json-path <local_dataset.json> \
  --revision main
```

## Python Conversion API

```python
from opensportslib.tools import convert_json_to_parquet, convert_parquet_to_json

convert_json_to_parquet(json_path="annotations.json", media_root=".", output_dir="out_parquet")
convert_parquet_to_json(dataset_dir="out_parquet", output_json_path="reconstructed.json")
```
