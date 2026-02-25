# SoccerNetPro Analyzer (UI)

[![Documentation Status](https://img.shields.io/badge/docs-online-brightgreen)](https://opensportslab.github.io/soccernetpro-ui/)

A **PyQt6-based GUI** for analyzing and annotating **SoccerNetPro / action spotting** datasets (OpenSportsLab).

---

## Features

- Open and visualize SoccerNetPro-style data and annotations.
- Annotate and edit events/actions with a user-friendly GUI.
- Manage labels/categories and export results for downstream tasks.
- Easy to extend with additional viewers, overlays, and tools.

---

## 🔧 Environment Setup

We recommend using [Anaconda](https://www.anaconda.com/) or [Miniconda](https://docs.conda.io/en/latest/miniconda.html) for managing your Python environment.

> **Note:** The GUI project lives in the `annotation_tool/` subdirectory of this repository, and dependencies are defined in `annotation_tool/requirements.txt`.

### Step 0 – Clone the repository

```bash
git clone https://github.com/OpenSportsLab/soccernetpro-ui.git
cd soccernetpro-ui
```


### Step 1 – Create a new Conda environment

```bash
conda create -n soccernetpro-ui python=3.9 -y
conda activate soccernetpro-ui
```


### Step 2 – Install dependencies
```bash
pip install -r annotation_tool/requirements.txt
```
---

## 🚀 Run the GUI
From the repository root, launch the app with:
```bash
python annotation_tool/main.py
```
A window will open where you can load your data and start working.


---


## 📦 Download Test Datasets

This project provides **test datasets** for multiple tasks, including:

- **Classification**
- **Localization**
- **Description (Video Captioning)**
- **Dense Description (Dense Video Captioning)**

More details are available at: [`/test_data`](https://github.com/OpenSportsLab/soccernetpro-ui/tree/main/test_data)

> ⚠️ **Important**
> For all tasks, the corresponding **JSON annotation file must be placed in the same directory**
> as the referenced data folders (e.g., `test/`, `germany_bundesliga/`, etc.).
> Otherwise, the GUI may not load the data correctly due to relative path mismatches.

Some Hugging Face datasets (including SoccerNetPro datasets) are **restricted / gated**. Therefore you must:

1. Have access to the dataset on Hugging Face
2. Be authenticated locally using your Hugging Face account (`hf auth login`)

---

### ✅ Requirements

- Python 3.x
- `huggingface_hub` (install via `pip install huggingface_hub`)

---

### 🧩 Universal Downloader (recommended)

We provide a single script that downloads **only the files referenced by a given JSON annotation file**:

- Downloads the JSON
- Parses `data[].inputs[].path` (and legacy `videos[].path`)
- Downloads the referenced files while preserving the repo folder structure

Script:

- `test_data/download_osl_hf.py`

Common usage:

```bash
python test_data/download_osl_hf.py \
  --url <HF_JSON_URL> \
  --output-dir <LOCAL_OUTPUT_DIR> \
  --types video
````

`--types` controls what input types to download from `item.inputs`:

* `video` (default)
* `video,captions`
* `video,captions,features`
* `all` (download all inputs that contain a `path`)

Use `--dry-run` to preview and estimate total size:

```bash
python test_data/download_osl_hf.py \
  --url <HF_JSON_URL> \
  --output-dir <LOCAL_OUTPUT_DIR> \
  --types video,captions,features \
  --dry-run
```

### 🟦 Classification – Test Data

**Data location (HuggingFace):**  
[Classification Dataset](https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars)

This folder contains multiple action-category subfolders (e.g. `action_0`, `action_1`, …).

#### 📥 Download via command line

**Classification – svfouls**

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/svfouls/annotations_test.json \
  --output-dir Test_Data/Classification/svfouls
```

**Classification – mvfouls**

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-classification-vars/blob/mvfouls/annotations_test.json \
  --output-dir Test_Data/Classification/mvfouls
```

### 🟩 Localization – Test Data
**Data location (HuggingFace):**  
- [Localization Dataset (Soccer)](https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snas)  
- [Localization Dataset (Tennis)](https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-tennis)

Each folder (e.g., `england efl/`) contains video clips for localization testing.

#### 📥 Download via command line

From the repository root:

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-localization-snbas/blob/224p/annotations-test.json \
  --output-dir Test_Data/Localization
```


## 🟪 Description (Video Captioning) – SoccerNet-XFoul
**Dataset (Hugging Face):**
[Description Dataset](https://huggingface.co/datasets/OpenSportsLab/soccernetpro-description-xfoul)

This dataset provides **video captioning** samples in OSL JSON format.
Each split JSON references clips under its corresponding folder:

* `annotations_train.json` → `train/`
* `annotations_valid.json` → `valid/`
* `annotations_test.json` → `test/`

### 📥 Download Test Split (videos only)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-description-xfoul/blob/main/annotations_test.json \
  --output-dir Test_Data/Description/XFoul \
  --types video
```

After download, you should have a structure like:

```
Test_Data/Description/XFoul/
  annotations_test.json
  test/
    action_0/
      clip_0.mp4
      clip_1.mp4
    ...
```

---

## 🟧 Dense Description (Dense Video Captioning) – SoccerNetPro SNDVC

**Dataset (Hugging Face):**
[Dense—Description Dataset](https://huggingface.co/datasets/OpenSportsLab/soccernetpro-densedescription-sndvc)


This dataset provides **dense captions aligned with timestamps** (half-relative), in a unified multimodal JSON format.
Each item typically references:

* half video (`.../1_224p.mp4` or `.../2_224p.mp4`)
* raw caption file (`.../Labels-caption.json`)
* optional visual features (e.g., `features/I3D/.../*.npy`)

### 📥 Download Test Split (videos only — recommended for GUI)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-densedescription-sndvc/blob/main/annotations-test.json \
  --output-dir Test_Data/DenseDescription/SNDVC \
  --types video
```

### 📥 Download Test Split (videos + raw captions + features)

```bash
python test_data/download_osl_hf.py \
  --url https://huggingface.co/datasets/OpenSportsLab/soccernetpro-densedescription-sndvc/blob/main/annotations-test.json \
  --output-dir Test_Data/DenseDescription/SNDVC \
  --types video,captions,features
```

Expected structure (example):

```
Test_Data/DenseDescription/SNDVC/
  annotations-test.json
  germany_bundesliga/
    2014-2015/
      <match_folder>/
        1_224p.mp4
        2_224p.mp4
        Labels-caption.json
  features/
    I3D/
      germany_bundesliga/...
        1_224p.npy
        2_224p.npy
```


---
## 🧰 Build a standalone app (PyInstaller)

This project can be packaged into a standalone desktop app using **PyInstaller**.
The commands below assume you run them **from the repository root**.

> **Note:** The app bundles runtime assets from `style/`, `ui/`, and `controllers/`.
> This matches the GitHub Actions build configuration.

---

### **macOS (.app)**

```bash
cd annotation_tool

python -m PyInstaller --noconfirm --clean --windowed \
  --name "SoccerNetProAnalyzer" \
  --add-data "style:style" \
  --add-data "ui:ui" \
  --add-data "controllers:controllers" \
  main.py
```

Output:

* `annotation_tool/dist/SoccerNetProAnalyzer.app`

---

### **Windows / Linux (one-file binary)**

#### Linux

```bash
cd annotation_tool

python -m PyInstaller --noconfirm --clean --windowed --onefile \
  --name "SoccerNetProAnalyzer" \
  --add-data "style:style" \
  --add-data "ui:ui" \
  --add-data "controllers:controllers" \
  main.py
```

Output:

* `annotation_tool/dist/SoccerNetProAnalyzer`


#### Windows (PowerShell)

On Windows, the `--add-data` separator is **`;`** (not `:`).

```powershell
cd annotation_tool

python -m PyInstaller --noconfirm --clean --windowed --onefile `
  --name "SoccerNetProAnalyzer" `
  --add-data "style;style" `
  --add-data "ui;ui" `
  --add-data "controllers;controllers" `
  main.py
```

Output:

* `annotation_tool\dist\SoccerNetProAnalyzer.exe`

---

## 🤖 How executables are built (CI / GitHub Releases)

In addition to manual PyInstaller builds, standalone executables are automatically built using GitHub Actions.

### Release builds (GitHub Releases)

When a version tag matching `v*` or `V*` (e.g., `v1.0.7`) is pushed, the release workflow runs:

* Workflow: `.github/workflows/release.yml`
* Builds for: **Windows**, **macOS**, **Linux**
* Packages outputs into ZIP archives
* Uploads ZIP files as **GitHub Release assets**
* Generates release notes from recent commit messages

The build commands in CI mirror the manual PyInstaller commands above (including bundling `style/`, `ui/`, and `controllers/`).

### Manual build artifacts (workflow dispatch)

There is also a standalone build workflow that can be triggered manually:

* Workflow: `.github/workflows/CL.yml`
* Builds for: **Windows**, **macOS**, **Linux**
* On **manual run** (`workflow_dispatch`), it zips the binaries and uploads them as **Actions artifacts** (short retention)

### CI workflows overview

* `CL.yml`: Multi-platform build (manual artifacts on `workflow_dispatch`; also runs on pushes to selected branches)
* `release.yml`: Multi-platform build + GitHub Release publishing (triggered by version tags)
* `deploy_docs.yml`: Documentation build and deployment (MkDocs)


---


## 📜 License

This Soccernet Pro project offers two licensing options to suit different needs:

* **AGPL-3.0 License**: This open-source license is ideal for students, researchers, and the community. It supports open collaboration and sharing. See the [`LICENSE.txt`](https://github.com/OpenSportsLab/soccernetpro-ui/blob/main/LICENSE.txt) file for full details.
* **Commercial License**: Designed for [`commercial use`](https://github.com/OpenSportsLab/soccernetpro-ui/blob/main/COMMERCIAL_LICENSE.md
), this option allows you to integrate this software into proprietary products and services without the open-source obligations of GPL-3.0. If your use case involves commercial deployment, please contact the maintainers to obtain a commercial license.

**Contact:** OpenSportsLab / project maintainers.




