import sys
import os
import re
import datetime as _datetime
import copy
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
        if isinstance(value, (bytes, bytearray)):
            try:
                value = value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        text = str(value or "").strip()
        if not text:
            return None
        if text.upper().endswith(" UTC"):
            text = f"{text[:-4].rstrip()}+00:00"
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = _datetime.datetime.fromisoformat(text)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(_datetime.timezone.utc).replace(tzinfo=None)
    return parsed


def format_utc_datetime(value):
    """Return the canonical JSON representation of a UTC instant."""
    parsed = parse_utc_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M:%S.%f") if parsed is not None else None


def annotation_utc_datetime(annotation, timeline_origin_utc):
    """Return an annotation's displayable UTC instant, including legacy projection."""
    if not isinstance(annotation, dict):
        return None
    if "timestamp_utc" in annotation:
        return parse_utc_datetime(annotation.get("timestamp_utc"))
    origin = parse_utc_datetime(timeline_origin_utc)
    if origin is None:
        return None
    return origin + _datetime.timedelta(
        milliseconds=annotation_position_ms(annotation, None)
    )


def format_annotation_utc_display(annotation, timeline_origin_utc):
    timestamp = annotation_utc_datetime(annotation, timeline_origin_utc)
    if timestamp is None:
        return None
    return f"{timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]} UTC"


def annotation_position_ms(annotation, timeline_origin_utc):
    """Resolve an annotation onto a sample timeline without mutating it."""
    if isinstance(annotation, dict):
        timestamp = parse_utc_datetime(annotation.get("timestamp_utc"))
        origin = parse_utc_datetime(timeline_origin_utc)
        if timestamp is not None and origin is not None:
            return int(round((timestamp - origin).total_seconds() * 1000.0))
        try:
            return int(annotation.get("position_ms", 0) or 0)
        except (TypeError, ValueError):
            pass
    return 0


def annotation_at_position(annotation, position_ms, timeline_origin_utc):
    """Return an annotation moved to a runtime position, including UTC when possible."""
    updated = copy.deepcopy(annotation) if isinstance(annotation, dict) else {}
    updated["position_ms"] = int(position_ms)
    origin = parse_utc_datetime(timeline_origin_utc)
    if origin is not None:
        updated["timestamp_utc"] = format_utc_datetime(
            origin + _datetime.timedelta(milliseconds=int(position_ms))
        )
    elif parse_utc_datetime(updated.get("timestamp_utc")) is not None:
        # A relative edit cannot truthfully retain an old absolute instant.
        updated.pop("timestamp_utc", None)
    return updated


def project_temporal_annotations(annotations, timeline_origin_utc):
    """Return UI copies with authoritative UTC timestamps projected to position_ms."""
    projected = []
    for annotation in list(annotations or []):
        if not isinstance(annotation, dict):
            continue
        item = copy.deepcopy(annotation)
        item["position_ms"] = annotation_position_ms(item, timeline_origin_utc)
        projected.append(item)
    return projected


def normalize_temporal_annotations_for_write(annotations, timeline_origin_utc):
    """Promote legacy annotations and refresh compatibility positions for JSON output."""
    origin = parse_utc_datetime(timeline_origin_utc)
    normalized = []
    for annotation in list(annotations or []):
        if not isinstance(annotation, dict):
            continue
        item = copy.deepcopy(annotation)
        timestamp = parse_utc_datetime(item.get("timestamp_utc"))
        if timestamp is not None:
            item["timestamp_utc"] = format_utc_datetime(timestamp)
            if origin is not None:
                item["position_ms"] = annotation_position_ms(item, origin)
        elif "timestamp_utc" not in item and origin is not None:
            item = annotation_at_position(item, annotation_position_ms(item, None), origin)
        normalized.append(item)
    return normalized


def temporal_annotation_identity(annotation, fields=()):
    """Build a stable matching key, preferring a valid absolute timestamp."""
    if not isinstance(annotation, dict):
        return None
    prefix = tuple(annotation.get(field) for field in fields)
    timestamp = format_utc_datetime(annotation.get("timestamp_utc"))
    if timestamp is not None:
        return prefix + ("utc", timestamp)
    return prefix + ("relative", annotation_position_ms(annotation, None))

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
