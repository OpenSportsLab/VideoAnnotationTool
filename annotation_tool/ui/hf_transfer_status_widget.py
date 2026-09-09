import re
from pathlib import PurePosixPath

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)


class HfDownloadStatusWidget(QWidget):
    """Compact, non-modal status-bar presentation for one HF download."""

    cancelRequested = pyqtSignal()
    _PROGRESS_PATTERN = re.compile(r"\[(\d+)/(\d+)\]")

    def __init__(self, message: str, *, split_count: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HfDownloadStatusWidget")
        self._split_count = max(0, int(split_count))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 0, 0)
        layout.setSpacing(6)

        self.label = QLabel(self)
        self.label.setMinimumWidth(180)
        self.label.setMaximumWidth(420)
        layout.addWidget(self.label, 1)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setObjectName("HfDownloadProgressBar")
        self.progress_bar.setAccessibleName("Hugging Face download progress")
        self.progress_bar.setFixedWidth(170)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("HfDownloadCancelButton")
        self.cancel_button.clicked.connect(self._request_cancel)
        layout.addWidget(self.cancel_button)

        self.set_message(message)

    def set_message(self, message: str) -> None:
        text = " ".join(str(message or "").splitlines()).strip()
        self.label.setText(f"HF Download: {text}")
        self.label.setToolTip(text)
        matches = [
            (int(current), int(total))
            for current, total in self._PROGRESS_PATTERN.findall(text)
            if int(total) > 0
        ]
        if not matches:
            return

        if self._split_count > 0:
            split_current, split_total = matches[0]
            split_total = max(split_total, self._split_count)
            if len(matches) > 1:
                item_current, item_total = matches[-1]
                fraction = (
                    max(0, split_current - 1)
                    + min(item_current, item_total) / item_total
                ) / split_total
            elif "complete" in text.lower():
                fraction = min(split_current, split_total) / split_total
            else:
                fraction = max(0, split_current - 1) / split_total
            self._set_fraction(fraction)
            return

        current, total = matches[-1]
        self.progress_bar.setRange(0, total)
        self.progress_bar.setValue(min(current, total))
        self.progress_bar.setFormat(f"{min(current, total)}/{total}")
        self.progress_bar.setTextVisible(True)

    def set_cancel_enabled(self, enabled: bool) -> None:
        self.cancel_button.setEnabled(bool(enabled))
        self.cancel_button.setText("Cancel" if enabled else "Cancelling...")

    def set_byte_progress(
        self, filename: str, downloaded_bytes: int, total_bytes: int
    ) -> None:
        downloaded = max(0, int(downloaded_bytes or 0))
        total = max(0, int(total_bytes or 0))
        display_name = PurePosixPath(str(filename or "file")).name or "file"
        if total:
            detail = f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
            self._set_fraction(min(downloaded, total) / total)
        else:
            detail = f"{_format_bytes(downloaded)} downloaded"
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setTextVisible(False)
        self.label.setText(f"HF Download: {display_name} — {detail}")
        self.label.setToolTip(f"{filename}\n{detail}")

    def _set_fraction(self, fraction: float) -> None:
        value = max(0, min(1000, int(round(float(fraction) * 1000))))
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat("%p%")
        self.progress_bar.setTextVisible(True)

    def _request_cancel(self) -> None:
        self.set_cancel_enabled(False)
        self.cancelRequested.emit()


def _format_bytes(byte_count: int) -> str:
    value = float(max(0, int(byte_count)))
    units = ("B", "KB", "MB", "GB", "TB")
    unit = units[0]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            break
        value /= 1024.0
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


__all__ = ["HfDownloadStatusWidget"]
