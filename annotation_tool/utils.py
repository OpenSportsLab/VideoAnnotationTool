import sys
import os
import re
import datetime as _datetime
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QIcon

# --- Constants ---
SUPPORTED_EXTENSIONS = (
    '.mp4', '.avi', '.mov',          # Video
    '.jpg', '.jpeg', '.png', '.bmp', # Image
    '.wav', '.mp3', '.aac'           # Audio
)

DEFAULT_TASK_NAME = "N/A (Please Import JSON)"
SINGLE_VIDEO_PREFIX = "Annotation_"


def parse_utc_datetime(value):
    """Parse an ISO-compatible UTC value into a naive UTC datetime."""
    if isinstance(value, _datetime.datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = _datetime.datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_datetime.timezone.utc).replace(tzinfo=None)
    return parsed

# --- Helper Functions ---
def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if hasattr(sys, "_MEIPASS"):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_square_remove_btn_style():
    """Returns CSS string for the small 'x' button."""
    return """
        QPushButton {
            background-color: transparent;
            border: 1px solid #999999;
            border-radius: 3px;
            color: #999999;
            font-family: Arial;
            font-weight: bold;
            font-size: 16px;
            padding: 0px;
            margin: 0px;
        }
        QPushButton:hover {
            border-color: #FF4444;
            color: #FF4444;
            background-color: rgba(255, 68, 68, 0.1);
        }
    """

def create_checkmark_icon(color):
    """Generates a dynamic checkmark icon."""
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent) 
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing) 
    pen = QPen(color)
    pen.setWidth(2) 
    pen.setCapStyle(Qt.PenCapStyle.RoundCap) 
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin) 
    painter.setPen(pen)
    points = [ QPointF(4, 9), QPointF(7, 12), QPointF(12, 5) ]
    painter.drawPolyline(points)
    painter.end()
    return QIcon(pixmap)

def natural_sort_key(s):
    """Key for natural sorting (e.g., File 1, File 2, File 10)."""
    # Safety check for None or non-string
    if not isinstance(s, str):
        return []
    return [int(text) if text.isdigit() else text.lower() for text in re.split('([0-9]+)', s)]
