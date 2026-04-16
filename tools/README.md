# Tools

Standalone command-line scripts for converting between the OSL JSON annotation format and a
Parquet + WebDataset representation suited for large-scale ML training pipelines.

---

## `osl_json_to_parquet_webdataset.py`

Converts an OSL-style JSON annotation file into:

- `metadata.parquet` — flattened per-sample metadata table.
- `shards/*.tar` — WebDataset TAR shards containing video files + per-sample sidecar JSON.
- `shard_manifest.parquet` — per-video-file manifest tracking shard membership and status.

### Usage

```bash
python tools/osl_json_to_parquet_webdataset.py <json_path> <media_root> <output_dir> [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `json_path` | Path to the OSL JSON annotation file. |
| `media_root` | Root directory containing the video files referenced in `inputs[].path`. |
| `output_dir` | Destination directory for the converted dataset. |

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--samples-per-shard N` | `100` | Number of samples packed into each TAR shard. |
| `--compression {zstd,snappy,gzip,brotli,none}` | `zstd` | Parquet compression codec. |
| `--shard-prefix PREFIX` | `shard` | File name prefix for TAR shard files. |
| `--missing-policy {raise,skip}` | `raise` | Action when a referenced video file is missing. `raise` aborts; `skip` omits the file from the shard but keeps the sample in Parquet. |
| `--absolute-paths` | off | Store resolved absolute paths in Parquet instead of the original relative paths. |
| `--overwrite` | off | Remove and recreate `output_dir` if it already exists. |

### Examples

```bash
# Basic conversion
python tools/osl_json_to_parquet_webdataset.py \
    annotations.json \
    /data/videos \
    /output/converted_dataset

# 50 samples per shard, skip missing files, overwrite existing output
python tools/osl_json_to_parquet_webdataset.py \
    annotations.json \
    /data/videos \
    /output/converted_dataset \
    --samples-per-shard 50 \
    --missing-policy skip \
    --overwrite
```

---

## `parquet_webdataset_to_osl_json.py`

Reconstructs an OSL-style JSON annotation file from a dataset directory previously created by
`osl_json_to_parquet_webdataset.py`.

Reconstruction is driven by the per-sample sidecar JSON stored inside each TAR shard, which is
the canonical full-fidelity annotation source. `metadata.parquet` is only used for routing
(locating the right shard) and lightweight filtering.

### Usage

```bash
python tools/parquet_webdataset_to_osl_json.py <dataset_dir> <output_json_path> [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `dataset_dir` | Directory produced by the forward converter (must contain `metadata.parquet` and `shards/`). |
| `output_json_path` | Destination path for the reconstructed OSL JSON file. |

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--extract-media` | off | Extract media files from TAR shards and rewrite `inputs[].path` to the extracted locations. |
| `--output-media-root DIR` | — | Directory to extract media files into. **Required** when `--extract-media` is set. |
| `--overwrite-media` | off | Overwrite already-extracted media files. |
| `--indent N` | `2` | JSON indentation level for the output file. |

### Examples

```bash
# Basic reconstruction
python tools/parquet_webdataset_to_osl_json.py \
    /output/converted_dataset \
    reconstructed_annotations.json

# Reconstruct and extract media files
python tools/parquet_webdataset_to_osl_json.py \
    /output/converted_dataset \
    reconstructed_annotations.json \
    --extract-media \
    --output-media-root /data/extracted_videos

# Custom indent
python tools/parquet_webdataset_to_osl_json.py \
    /output/converted_dataset \
    reconstructed_annotations.json \
    --indent 4
```

---

## Round-trip example

```bash
# Forward pass: JSON → Parquet + WebDataset
python tools/osl_json_to_parquet_webdataset.py \
    test_data/Localization/gymnastics/annotations.json \
    test_data/Localization/gymnastics \
    /tmp/gymnastics_wds \
    --overwrite

# Backward pass: Parquet + WebDataset → JSON
python tools/parquet_webdataset_to_osl_json.py \
    /tmp/gymnastics_wds \
    /tmp/gymnastics_reconstructed.json



# Description
python tools/osl_json_to_parquet_webdataset.py \
    test_data/Description/xfoul/annotations_test.json \
    test_data/Description/xfoul \
    test_data/xfoul_parquet_webdataset \
    --samples-per-shard 50 \
    --missing-policy skip \
    --overwrite

python tools/parquet_webdataset_to_osl_json.py \
    test_data/xfoul_parquet_webdataset \
    test_data/xfoul_parquet_webdataset_back_to_json/reconstructed_annotations.json \
    --extract-media \
    --output-media-root test_data/xfoul_parquet_webdataset_back_to_json \
    --indent 2


# Classification
python tools/osl_json_to_parquet_webdataset.py \
    test_data/Classification/svfouls/annotations_test.json \
    test_data/Classification/svfouls \
    test_data/svfouls_parquet_webdataset \
    --samples-per-shard 50 \
    --missing-policy skip \
    --overwrite

python tools/parquet_webdataset_to_osl_json.py \
    test_data/svfouls_parquet_webdataset \
    test_data/svfouls_parquet_webdataset_back_to_json/reconstructed_annotations.json \
    --extract-media \
    --output-media-root test_data/svfouls_parquet_webdataset_back_to_json \
    --indent 2
```

## Dependencies

Both scripts require `pandas` and `pyarrow`. Install all project dependencies with:

```bash
pip install -r requirements.txt
```
