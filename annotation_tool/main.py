import os
import sys
import multiprocessing

os.environ["PYTORCH_JIT"] = "0"

# Xet's Rust transfer backend can raise unhelpful low-level timeouts
# ("Timeout: Request error: ... domain: no-url") on slow/large HF uploads.
# Disable it by default so huggingface_hub falls back to its classic,
# more resilient HTTP upload path. Must be set before huggingface_hub
# is imported (it reads this env var at import time). An explicit
# HF_HUB_DISABLE_XET already set in the environment takes precedence.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from PyQt6.QtWidgets import QApplication
from main_window import VideoAnnotationWindow

if __name__ == '__main__':
    multiprocessing.freeze_support()
    
    app = QApplication(sys.argv)
    window = VideoAnnotationWindow()
    window.show()
    sys.exit(app.exec())