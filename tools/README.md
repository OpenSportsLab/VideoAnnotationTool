# Tools

Standalone command-line scripts for OSL JSON annotation conversion and dataset preparation.

---

## `convert_dataset_videos_to_224p.py`

Converts every video input referenced by an OSL-style JSON annotation file to 224p copies,
preserving aspect ratio and writing a new JSON file that points at the converted videos.

The output videos keep the same relative folder structure under `output_media_root`.
Non-video inputs and all annotation fields are preserved unchanged.
If FFmpeg fails for a specific video, the tool skips that file, continues with the
remaining videos, removes any partial output for that failed file, and prints the
failed source/output paths at the end.

### Usage

```bash
python tools/convert_dataset_videos_to_224p.py <json_path> <media_root> <output_json_path> <output_media_root> [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `json_path` | Path to the source OSL JSON annotation file. |
| `media_root` | Root directory containing the files referenced in `inputs[].path`. |
| `output_json_path` | Destination path for the converted dataset JSON. |
| `output_media_root` | Destination root for the converted video files. |

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--height N` | `224` | Target output video height. Width is chosen by FFmpeg to preserve aspect ratio with an encoder-compatible even value. |
| `--fps FPS` | `25` | Forced output video frame rate. |
| `--overwrite` | off | Replace existing output JSON and video files. |
| `--missing-policy {raise,skip}` | `raise` | Action when a referenced source video is missing. |
| `--dry-run` | off | Print planned conversions without writing JSON or media. |

### Examples

```bash
# Convert a dataset to a parallel 224p media root
python tools/convert_dataset_videos_to_224p.py \
    test_data/VQA/XFoul-train/train.json \
    test_data/VQA/XFoul-train \
    test_data/VQA/XFoul-train-224p/train.json \
    test_data/VQA/XFoul-train-224p \
    --overwrite

# Preview conversions without writing files
python tools/convert_dataset_videos_to_224p.py \
    test_data/VQA/XFoul-test/test.json \
    test_data/VQA/XFoul-test \
    test_data/VQA/XFoul-test-224p/test.json \
    test_data/VQA/XFoul-test-224p \
    --dry-run
```

---

## `upload_dataset_to_hf.py`

Uploads an OSL dataset to Hugging Face using `opensportslib.tools.hf_transfer`.

The default mode uploads the dataset JSON plus every file referenced in `data[].inputs[].path`,
preserving the paths declared in the JSON. The Parquet mode uploads the dataset as
Parquet + WebDataset shards through the OpenSportsLib upload API.
If the target dataset repo or branch/revision does not exist, the tool creates it and retries
the upload once.

### Usage

```bash
python tools/upload_dataset_to_hf.py --repo-id <org/repo> --json-path <json_path> [options]
```

### Required arguments

| Flag | Description |
|---|---|
| `--repo-id REPO` | Target Hugging Face dataset repo ID, such as `OpenSportsLab/my-dataset`. |
| `--json-path PATH` | Local OSL dataset JSON path. |

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--revision REV` | `main` | Target branch/revision in the dataset repo. |
| `--commit-message MSG` | `Upload dataset inputs from JSON` | Commit message for the upload. |
| `--token TOKEN` | — | Optional Hugging Face token. If omitted, local HF login is used. |
| `--format {json,parquet}` | `json` | Upload JSON + referenced inputs, or Parquet + WebDataset shards. |
| `--shard-mode {size,samples}` | `size` | Shard grouping mode for `--format parquet`. |
| `--shard-size SIZE` | `1GB` | Target TAR shard size for `--format parquet`. Supports values like `500MB`, `1GB`, `1024MiB`, or plain bytes. |

### Examples

```bash
# Upload the JSON dataset and referenced input files
python tools/upload_dataset_to_hf.py \
    --repo-id OpenSportsLab/OSL-loc-tennis-public \
    --json-path test_data/VQA/XFoul-test/test.json \
    --commit-message "Upload XFoul test dataset"

# Upload as Parquet + WebDataset shards
for split in test valid train; do
python tools/upload_dataset_to_hf.py \
    --repo-id OpenSportsLab/OSL-XFoul \
    --revision 224p \
    --json-path test_data/VQA/XFoul-$split-224p/$split.json \
    --format parquet \
    --shard-size 1GB \
    --commit-message "Upload XFoul $split 224p dataset"

python tools/upload_dataset_to_hf.py \
    --repo-id OpenSportsLab/OSL-XFoul \
    --revision 720p \
    --json-path test_data/VQA/XFoul-$split/$split.json \
    --format parquet \
    --shard-size 1GB \
    --commit-message "Upload XFoul $split 720p dataset"
done
```

---

## `osl_json_to_parquet_webdataset.py`

Converts an OSL-style JSON annotation file into:

- `metadata.parquet` — flattened per-sample metadata table.
- `shards/*.tar` — WebDataset TAR shards containing input files + per-sample sidecar JSON.
- `shard_manifest.parquet` — per-input-file manifest tracking shard membership and status.

### Usage

```bash
python tools/osl_json_to_parquet_webdataset.py <json_path> <media_root> <output_dir> [options]
```

### Positional arguments

| Argument | Description |
|---|---|
| `json_path` | Path to the OSL JSON annotation file. |
| `media_root` | Root directory containing the files referenced in `inputs[].path`. |
| `output_dir` | Destination directory for the converted dataset. |

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--shard-mode {size,samples}` | `size` | Group samples by target TAR size or by sample count. |
| `--shard-size SIZE` | `1GB` | Target TAR shard size in size mode. Supports values like `500MB`, `1GB`, `1024MiB`, or plain bytes. |
| `--samples-per-shard N` | `100` | Number of samples packed into each TAR shard when `--shard-mode samples` is used. |
| `--compression {zstd,snappy,gzip,brotli,none}` | `zstd` | Parquet compression codec. |
| `--shard-prefix PREFIX` | `shard` | File name prefix for TAR shard files. |
| `--missing-policy {raise,skip}` | `raise` | Action when a referenced input file is missing. `raise` aborts; `skip` omits the file from the shard but keeps the sample in Parquet. |
| `--absolute-paths` | off | Store resolved absolute paths in Parquet instead of the original relative paths. |
| `--overwrite` | off | Remove and recreate `output_dir` if it already exists. |

### Examples

```bash
# Basic conversion
python tools/osl_json_to_parquet_webdataset.py \
    annotations.json \
    /data/videos \
    /output/converted_dataset

# 500 MB shards, skip missing files, overwrite existing output
python tools/osl_json_to_parquet_webdataset.py \
    annotations.json \
    /data/videos \
    /output/converted_dataset \
    --shard-size 500MB \
    --missing-policy skip \
    --overwrite
```

---

## `merge_mvfouls_classification_into_vqa.py`

Copies MVFouls classification labels into XFoul VQA annotation samples. The script matches
samples by ID, stripping the MVFouls `test_` prefix and applying labels to duplicate VQA
samples with suffixes such as `__2` or `__3`.

### Usage

```bash
python tools/merge_mvfouls_classification_into_vqa.py [options]
```

### Optional arguments

| Flag | Default | Description |
|---|---|---|
| `--classification-json PATH` | `test_data/MVFouls/test/annotations_test.json` | Path to the MVFouls classification annotation JSON. |
| `--vqa-json PATH` | `test_data/VQA/XFoul-test/test.json` | Path to the XFoul VQA annotation JSON. |
| `--output-json PATH` | `test_data/VQA/XFoul-test/test_with_classification.json` | Path where the merged JSON should be written. |
| `--indent N` | `2` | JSON indentation level for the output file. |

### Examples

```bash
# Merge using the default repository test-data paths
python tools/merge_mvfouls_classification_into_vqa.py

# Merge explicit input/output files
python tools/merge_mvfouls_classification_into_vqa.py \
    --classification-json test_data/MVFouls/test/annotations_test.json \
    --vqa-json test_data/VQA/XFoul-test/test.json \
    --output-json test_data/VQA/XFoul-test/test_with_classification.json

python tools/merge_mvfouls_classification_into_vqa.py \
    --classification-json test_data/MVFouls-jsonly/annotations_valid.json \
    --vqa-json test_data/VQA/XFoul-valid/valid.json \
    --output-json test_data/VQA/XFoul-valid/valid_with_classification.json

python tools/merge_mvfouls_classification_into_vqa.py \
    --classification-json test_data/MVFouls-jsonly/annotations_train.json \
    --vqa-json test_data/VQA/XFoul-train/train.json \
    --output-json test_data/VQA/XFoul-train/train_with_classification.json
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
| `--extract-media` | off | Extract media files from TAR shards into `output_media_root/<original_path>` while preserving `inputs[].path` unchanged, so the reconstructed paths remain valid relative paths. |
| `--output-media-root DIR` | — | Root directory to extract media files into, preserving each original `inputs[].path` underneath it. **Required** when `--extract-media` is set. |
| `--overwrite-media` | off | Overwrite already-extracted media files under `output_media_root/<original_path>`. |
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
    --shard-size 500MB \
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
    --shard-size 500MB \
    --missing-policy skip \
    --overwrite

python tools/parquet_webdataset_to_osl_json.py \
    test_data/svfouls_parquet_webdataset \
    test_data/svfouls_parquet_webdataset_back_to_json/reconstructed_annotations.json \
    --extract-media \
    --output-media-root test_data/svfouls_parquet_webdataset_back_to_json \
    --indent 2
    

# SN-GAR-tracking
python tools/osl_json_to_parquet_webdataset.py \
    test_data/sngar-tracking/annotations_test.json \
    test_data/sngar-tracking \
    test_data/sngar-tracking_parquet_webdataset \
    --shard-size 500MB \
    --missing-policy skip \
    --overwrite

python tools/parquet_webdataset_to_osl_json.py \
    test_data/sngar-tracking_parquet_webdataset \
    test_data/sngar-tracking_parquet_webdataset_back_to_json/reconstructed_annotations.json \
    --extract-media \
    --output-media-root test_data/sngar-tracking_parquet_webdataset_back_to_json \
    --indent 2


```

## Dependencies

Both scripts require `opensportslib` latest version

```bash
pip install opensportslib==0.1.3
pip install -e ~/git/opensportslib/
```
