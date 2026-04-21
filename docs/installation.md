# Installation

## Option 1: Use Pre-Built Binaries

Pre-built binaries for macOS, Windows, and Linux are available on GitHub Releases:

- https://github.com/OpenSportsLab/VideoAnnotationTool/releases

Download the asset for your platform and run it directly.

## Option 2: Install From Source

## Requirements

- Python 3.12 recommended
- A working Qt multimedia backend (installed with PyQt6)

```bash
git clone https://github.com/OpenSportsLab/VideoAnnotationTool.git
cd VideoAnnotationTool
```

Create and activate an environment:

```bash
conda create -n VideoAnnotationTool python=3.12 -y
conda activate VideoAnnotationTool
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the app:

```bash
python annotation_tool/main.py
```

## Optional Setup

- Hugging Face access for gated datasets:

```bash
huggingface-cli login
```

- If some videos fail to decode, install FFmpeg and transcode unsupported files to H.264 MP4 (see [Troubleshooting](troubleshooting.md)).
