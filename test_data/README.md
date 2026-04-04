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
  --url https://huggingface.co/datasets/<org>/<dataset>/blob/<revision>/<annotations.json> \
  --output-dir <output_directory>
```
- The URL should be copied directly from the Hugging Face web interface
(i.e. `blob/... URLs`).
- The script automatically converts it to the correct `resolve/...` format internally.

**Arguments:**

* `--url`: (required) The direct Hugging Face URL of the OSL JSON file (should be in “blob/main/...” form, like you see in the web interface).
* `--output-dir`: (optional) Path to the directory where the dataset and videos should be downloaded. Defaults to `downloaded_data` if not specified.
* `--dry-run`: (optional) If provided, lists all files that would be downloaded and total size, but does not actually download any files.


**Example:**
Classification – svfouls

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/svfouls/annotations_test.json \
  --output-dir test_data/Classification/svfouls
```

Classification – mvfouls

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/mvfouls/annotations_test.json \
  --output-dir test_data/Classification/mvfouls
```

Localization – Action Spotting (SNBAS)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snbas/blob/224p/annotations-test.json \
  --output-dir test_data/Localization/snbas
```

Localization – Action Spotting (Tennis)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-tennis/blob/main/annotations-localization-test.json \
  --output-dir test_data/Localization/tennis
```

Localization – Action Spotting (Gymnastics)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-gymnastics/blob/main/annotations-localization-test.json \
  --output-dir test_data/Localization/gymnastics
```

Description – Video Captioning (xFoul)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-description-xfoul/blob/main/annotations_test.json \
  --output-dir test_data/Description/xfoul
```

Dense Description – Dense Video Captioning (SNDVC)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-densedescription-sndvc/blob/main/annotations-test.json \
  --output-dir test_data/DenseDescription/sndvc
```

**Dry Run Example:**
Before downloading large video files, run the script in dry-run mode
```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/svfouls/annotations_test.json \
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

### **Notes**

* The script automatically converts Hugging Face “blob” URLs to the proper “resolve” format for direct file access.
* After downloading, the output directory will contain the JSON annotation and all video files referenced in it, keeping the original folder structure.
* For datasets with a large number of videos, downloads will be parallelized for efficiency.
* If a video is missing in the repo, it will be reported (especially useful in dry run mode).
