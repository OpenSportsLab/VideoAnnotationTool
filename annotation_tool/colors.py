import colorsys
import hashlib


def localization_label_color_hex(head: str, label: str, label_colors: dict | None = None) -> str:
    if isinstance(label_colors, dict):
        override = normalize_hex_color(label_colors.get(str(label or "")))
        if override:
            return override

    clean_head = str(head or "").strip().lower()
    clean_label = str(label or "").strip().lower()
    color_key = f"{clean_head}:{clean_label}".strip(":")
    if not color_key:
        return "#00bfff"

    digest = hashlib.sha1(color_key.encode("utf-8")).hexdigest()
    hue = int(digest[:8], 16) % 360
    red, green, blue = colorsys.hls_to_rgb(hue / 360.0, 0.58, 0.62)
    return f"#{int(red * 255):02x}{int(green * 255):02x}{int(blue * 255):02x}"


def localization_label_text_hex(color_hex: str) -> str:
    red, green, blue = _hex_to_rgb(color_hex)
    luminance = (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255.0
    return "#111111" if luminance > 0.62 else "#f6f6f6"


def normalize_hex_color(color_hex: str | None) -> str | None:
    normalized = str(color_hex or "").strip().lower()
    if not normalized:
        return None
    if not normalized.startswith("#"):
        normalized = f"#{normalized}"
    if len(normalized) != 7:
        return None
    try:
        int(normalized[1:], 16)
    except ValueError:
        return None
    return normalized


def localization_label_hover_hex(color_hex: str) -> str:
    return _adjust_color(color_hex, 1.08)


def localization_label_pressed_hex(color_hex: str) -> str:
    return _adjust_color(color_hex, 0.86)


def _hex_to_rgb(color_hex: str) -> tuple[int, int, int]:
    normalized = str(color_hex or "").strip().lstrip("#")
    if len(normalized) != 6:
        return (0, 191, 255)
    return tuple(int(normalized[idx:idx + 2], 16) for idx in (0, 2, 4))


def _adjust_color(color_hex: str, factor: float) -> str:
    red, green, blue = _hex_to_rgb(color_hex)
    scaled = [max(0, min(255, int(channel * factor))) for channel in (red, green, blue)]
    return f"#{scaled[0]:02x}{scaled[1]:02x}{scaled[2]:02x}"