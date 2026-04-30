## test_data Directory Usage

The `test_data` directory contains utility scripts to help you work with OSL (Open Sports Lab) datasets, particularly for downloading annotated datasets and associated videos from Hugging Face. Below you'll find an explanation and usage instructions.

---

### 1. Download OSL Dataset and Videos from Hugging Face

**Script:** `test_data/download_osl_hf.py`

This script automates the download of an OSL-format JSON file (annotation file) and all referenced videos from a Hugging Face dataset repository.

#### **Features:**

* Downloads a specific OSL JSON annotation file.
* Parses the JSON to identify referenced video files and downloads them as well.
* Can perform a “dry run” to show which files would be downloaded and their total size, without actually downloading.


#### ⚠️ Authentication Required for Gated Datasets
Some Hugging Face datasets (including opensportslib localization and classification datasets) are restricted / gated.

To download files from these datasets, you must:

1.Have access to the dataset on Hugging Face

2.Be authenticated locally using your Hugging Face account

#### Login to Hugging Face (Required)
Before running the script, authenticate once on your machine:
```bash
huggingface-cli login
```
<img width="1182" height="710" alt="b6a32f46-9962-49cc-9882-a5dba710d606" src="https://github.com/user-attachments/assets/d848f451-58f6-40c6-96e3-e65cde7b4dc1" />

Follow the instructions to paste your Hugging Face access token.

You can verify that authentication is working with:

```bash
python -c "from huggingface_hub import HfApi; print(HfApi().whoami())"
```

If authentication is missing or access is not granted, the script will fail with a
`GatedRepoError (401)`.

#### **Requirements**

* Python 3.x
* `huggingface_hub` Python package (install with `pip install huggingface_hub`)

#### **Usage**


**Basic Command:**

```bash
python test_data/download_osl_hf.py \
  --repo-id <org>/<dataset> \
  --revision <revision> \
  --split <split> \
  --format json \
  --output-dir <output_directory>
```
- JSON mode downloads `<split>.json` and every file referenced by that JSON.
- Parquet mode downloads and converts the `<split>/` folder.

**Arguments:**

* `--repo-id`: (required) Hugging Face dataset repo ID, such as `OpenSportsLab/OSL-XFoul`.
* `--revision`: (required) Hugging Face branch/revision.
* `--split`: (required) Split/artifact name.
* `--format`: (optional) `json` or `parquet`. Defaults to `parquet`.
* `--output-dir`: (optional) Download root. Files are written under `<output-dir>/<revision>/<split>`. Defaults to `downloaded_data`.
* `--dry-run`: (optional) If provided, lists all files that would be downloaded and total size, but does not actually download any files.
* `--token`: (optional) HF token override. If omitted, your local HF login is used.


**Example:**
Classification – svfouls

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-classification-vars \
  --revision svfouls \
  --split annotations_test \
  --format json \
  --output-dir test_data/Classification/svfouls
```

Classification – mvfouls

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-classification-vars \
  --revision mvfouls \
  --split annotations_test \
  --format json \
  --output-dir test_data/Classification/mvfouls
```

Localization – Action Spotting (SNBAS)

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-localization-snbas \
  --revision 224p \
  --split annotations-test \
  --format json \
  --output-dir test_data/Localization/snbas
```

Localization – Action Spotting (Tennis)

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-localization-tennis \
  --revision main \
  --split annotations-localization-test \
  --format json \
  --output-dir test_data/Localization/tennis
```

Localization – Action Spotting (Gymnastics)

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-localization-gymnastics \
  --revision main \
  --split annotations-localization-test \
  --format json \
  --output-dir test_data/Localization/gymnastics
```

Description – Video Captioning (xFoul)

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-description-xfoul \
  --revision main \
  --split annotations_test \
  --format json \
  --output-dir test_data/Description/xfoul
```

Dense Description – Dense Video Captioning (SNDVC)

```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-densedescription-sndvc \
  --revision main \
  --split annotations-test \
  --format json \
  --output-dir test_data/DenseDescription/sndvc
```

**Dry Run Example:**
Before downloading large video files, run the script in dry-run mode
```bash
python test_data/download_osl_hf.py \
  --repo-id OpenSportsLab/soccernetpro-classification-vars \
  --revision svfouls \
  --split annotations_test \
  --format json \
  --dry-run
```
Dry-run mode will:
- List all video files that would be downloaded
- Show the estimated total storage required
- Report missing files (if any)
- Download nothing

---

**Output Structure:**
Output Structure
After downloading, the output directory will contain:
- The annotation JSON file
- All referenced video files
- The original Hugging Face repository folder structure


Example:

```bash
output_dir/
├── annotations-test.json
└── test/
    └── action_0/
        ├── clip_0.mp4
        └── clip_1.mp4
```


### 2. Zip the folder(Optional)

```bash
zip -r DatasetAnnotationTool.zip *
```

---

### 3. Convert SoccerNet-XFoul Row QA to OSL Q/A (+ optional media download)

**Script:** `test_data/convert_xfoul_to_qa.py`

Converts row-wise XFoul annotations (`path`, `video1..videoN`, `question`, `answer`) into one OSL Q/A dataset JSON:
- `path` tail becomes sample id (e.g., `Test/action_0` -> `action_0`)
- `video1..videoN` become multiview `inputs[]`
- if `video*` differs across duplicated rows of the same sample, the row with the most videos is used
- repeated answers for the same source sample/question are grouped under `answers[].answers`
- question text is stored in each sample next to its answers; no top-level `questions` bank is written

**Usage (JSON only, no download):**

```bash
# test split
python test_data/convert_xfoul_to_qa.py \
  --input-json test_data/SoccerNet-XFoul/annotations_test.json \
  --output-json test_data/VQA/XFoul-test/test.json \
  --media-dir test \
  --skip-download

# train split
python test_data/convert_xfoul_to_qa.py \
  --input-json test_data/SoccerNet-XFoul/annotations_train.json \
  --output-json test_data/VQA/XFoul-train/train.json \
  --media-dir train \
  --skip-download

# valid split
python test_data/convert_xfoul_to_qa.py \
  --input-json test_data/SoccerNet-XFoul/annotations_valid.json \
  --output-json test_data/VQA/XFoul-valid/valid.json \
  --media-dir valid \
  --skip-download
```

**Usage (JSON + download media):**

```bash
python test_data/convert_xfoul_to_qa.py \
  --input-json test_data/SoccerNet-XFoul/annotations_test.json \
  --output-json test_data/VQA/XFoul/test.json \
  --media-dir media
```

**Arguments:**
- `--input-json` (required): source row-wise JSON file.
- `--output-json` (required): converted OSL Q/A JSON path.
- `--media-dir` (optional): relative directory used in `inputs[].path` (default: `media`).
- `--skip-download` (optional): build output JSON only.
- `--overwrite` (optional): overwrite existing local media files when downloading.

If some media URLs fail during download (e.g., HTTP 403), conversion continues for remaining files and writes a
`<output_json_stem>_download_failures.txt` report next to the output JSON.

To migrate older VQA JSON files that use root `questions` plus `question_id` answers, run:

```bash
python tools/convert_legacy_vqa_to_grouped.py \
  --input-json test_data/VQA/XFoul-test/test_old.json \
  --output-json test_data/VQA/XFoul-test/test.json
```

---

### 4. Upload Inputs Referenced by a Local Dataset JSON to Hugging Face

**Script:** `test_data/upload_osl_hf.py`

Use this script to upload files referenced in `data[].inputs[].path` from a local dataset JSON.
Inputs are batched and uploaded in a single Hugging Face commit request, preserving the exact paths declared in the JSON.

```bash
python test_data/upload_osl_hf.py \
  --repo-id OpenSportsLab/OSL-loc-tennis-public \
  --json-path /Users/quirogky/Projects/TennisLocalization/annotations_train.json \
  --commit-message "Update inputs from annotations JSON"
```

**Arguments:**

* `--repo-id`: (required) Target Hugging Face dataset repo ID (`org/repo`).
* `--json-path`: (required) Local dataset JSON path.
* `--commit-message`: (optional) Commit message prefix. Defaults to `Upload dataset inputs from JSON`.
* `--token`: (optional) HF token override. If omitted, your local HF login is used.

---

### 5. GUI Support (Data Menu)

Inside the application menu bar, there is now a **Data** menu with:

* **Download Dataset from HF...**
* **Upload Dataset to HF...**

Both actions open a dialog to enter the minimum required fields plus common optional parameters.
Downloads and uploads run in background threads, and after a successful download you can choose to open the downloaded JSON directly in the app.
For upload, the dialog asks for a dataset JSON path and pushes all `data[].inputs[].path` entries in one batched commit.

---

### **Notes**

* The script automatically converts Hugging Face “blob” URLs to the proper “resolve” format for direct file access.
* After downloading, the output directory will contain the JSON annotation and all video files referenced in it, keeping the original folder structure.
* For datasets with a large number of videos, downloads will be parallelized for efficiency.
* If a video is missing in the repo, it will be reported (especially useful in dry run mode).
