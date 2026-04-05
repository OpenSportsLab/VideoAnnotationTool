# Installation

**Quick option:**

Pre-built binaries for Windows, macOS, and Linux are available on the [GitHub Releases page](https://github.com/OpenSportsLab/VideoAnnotationTool/releases). Download the latest release for your platform and run the executable—no installation required.

---

## Requirements

- Python **3.11** or later
- PyQt6
- Other dependencies (see `requirements.txt`)

---

## Steps (from source)

> **Note:** The PyQt GUI project lives in the `annotation_tool/` subdirectory of this repository. All commands below assume you are running them from the repository root unless stated otherwise.

1. **Clone the repository**
   ```bash
   git clone https://github.com/OpenSportsLab/VideoAnnotationTool.git
   cd VideoAnnotationTool
   ```

2. **(Recommended) Create and activate a Conda environment**
   ```bash
   conda create -n VideoAnnotationTool python=3.9 -y
   conda activate VideoAnnotationTool
   ```

4. **Install dependencies:**
    The main dependencies are:
    - pyqt6
    - opencv-python (optional, for video rendering/computer vision)
    - See `requirements.txt` for the full list
    
    Install with pip:
   
    ```bash
    pip install pyqt6
    
    # Optional, for video rendering/computer vision:
    pip install opencv-python
    
    # Or install all dependencies:
    pip install -r requirements.txt
    ```

6. **Run the tool:**
    ```bash
    python annotation_tool/main.py
    ```

## Troubleshooting

- If you have issues with Qt or video playback, check [Troubleshooting](troubleshooting.md).
