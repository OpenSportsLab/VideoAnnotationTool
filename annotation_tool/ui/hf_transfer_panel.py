"""Presentation-only panel for the active Hugging Face dataset transfer."""

from __future__ import annotations

import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class HfTransferPanel(QWidget):
    """Show overall and current-file progress without blocking annotation work."""

    cancelRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    _PROGRESS_PATTERN = re.compile(r"\[(\d+)/(\d+)\]")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HfTransferPanel")
        self._split_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.state_label = QLabel("No recent Hugging Face transfer", self)
        self.state_label.setObjectName("hfTransferState")
        self.state_label.setWordWrap(True)
        header.addWidget(self.state_label, 1)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("hfTransferCancelButton")
        self.cancel_button.clicked.connect(self._request_cancel)
        header.addWidget(self.cancel_button)
        self.clear_button = QPushButton("Clear", self)
        self.clear_button.setObjectName("hfTransferClearButton")
        self.clear_button.clicked.connect(self.clearRequested.emit)
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        self.stage_label = QLabel("Waiting for transfer progress.", self)
        self.stage_label.setObjectName("hfTransferStage")
        self.stage_label.setWordWrap(True)
        layout.addWidget(self.stage_label)

        self.overall_label = QLabel("Overall progress", self)
        layout.addWidget(self.overall_label)
        self.overall_progress_bar = self._create_progress_bar(
            "hfTransferOverallProgress", "Hugging Face overall download progress"
        )
        layout.addWidget(self.overall_progress_bar)

        self.current_file_label = QLabel("Current file: —", self)
        self.current_file_label.setObjectName("hfTransferCurrentFile")
        self.current_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.current_file_label)
        self.file_progress_bar = self._create_progress_bar(
            "hfTransferFileProgress", "Hugging Face current file download progress"
        )
        layout.addWidget(self.file_progress_bar)

        self.summary_label = QLabel("", self)
        self.summary_label.setObjectName("hfTransferSummary")
        self.summary_label.setWordWrap(True)
        self.summary_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.summary_label)
        layout.addStretch(1)
        self.clear_summary()

    @staticmethod
    def _create_progress_bar(object_name: str, accessible_name: str) -> QProgressBar:
        progress_bar = QProgressBar()
        progress_bar.setObjectName(object_name)
        progress_bar.setAccessibleName(accessible_name)
        progress_bar.setRange(0, 0)
        progress_bar.setTextVisible(False)
        return progress_bar

    def begin(self, message: str, *, split_count: int = 0, operation: str = "") -> None:
        self._split_count = max(0, int(split_count))
        self.state_label.setText(operation or "Hugging Face download in progress")
        self.stage_label.setText(self._one_line(message) or "Starting transfer…")
        self.overall_label.setText("Overall progress: waiting for item count")
        self._set_indeterminate(self.overall_progress_bar)
        self.current_file_label.setText("Current file: waiting for file transfer")
        self.current_file_label.setToolTip("")
        self._set_indeterminate(self.file_progress_bar)
        self.summary_label.clear()
        self.cancel_button.setVisible(True)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.clear_button.setVisible(False)

    def set_stage_progress(self, message: str) -> None:
        text = self._one_line(message)
        if not text:
            return
        self.stage_label.setText(text)
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
            self._set_fraction(self.overall_progress_bar, fraction)
            self.overall_label.setText(
                f"Overall progress: {min(split_current, split_total)} / {split_total} splits"
            )
            return

        current, total = matches[-1]
        self._set_count_progress(self.overall_progress_bar, current, total)
        self.overall_label.setText(
            f"Overall progress: {min(current, total)} / {total} items"
        )

    def set_file_progress(
        self, filename: str, downloaded_bytes: int, total_bytes: int
    ) -> None:
        downloaded = max(0, int(downloaded_bytes or 0))
        total = max(0, int(total_bytes or 0))
        path = str(filename or "file")
        if total:
            detail = f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
            self._set_fraction(self.file_progress_bar, downloaded / total)
        else:
            detail = f"{_format_bytes(downloaded)} downloaded"
            self._set_indeterminate(self.file_progress_bar)
        self.current_file_label.setText(f"Current file: {path} — {detail}")
        self.current_file_label.setToolTip(f"{path}\n{detail}")

    def set_cancelling(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")

    def set_terminal(self, state: str, summary: str) -> None:
        self.state_label.setText(state)
        self.stage_label.setText("The transfer is no longer running.")
        self.summary_label.setText(str(summary or ""))
        self.cancel_button.setVisible(False)
        self.clear_button.setVisible(True)

    def clear_summary(self) -> None:
        self._split_count = 0
        self.state_label.setText("No recent Hugging Face transfer")
        self.stage_label.setText("Start a dataset download to see progress here.")
        self.overall_label.setText("Overall progress: —")
        self.current_file_label.setText("Current file: —")
        self.current_file_label.setToolTip("")
        self.summary_label.clear()
        self._set_indeterminate(self.overall_progress_bar)
        self._set_indeterminate(self.file_progress_bar)
        self.cancel_button.setVisible(False)
        self.clear_button.setVisible(False)

    @staticmethod
    def _one_line(message: str) -> str:
        return " ".join(str(message or "").splitlines()).strip()

    @staticmethod
    def _set_indeterminate(progress_bar: QProgressBar) -> None:
        progress_bar.setRange(0, 0)
        progress_bar.setTextVisible(False)

    @staticmethod
    def _set_count_progress(progress_bar: QProgressBar, current: int, total: int) -> None:
        maximum = max(1, int(total))
        value = min(max(0, int(current)), maximum)
        progress_bar.setRange(0, maximum)
        progress_bar.setValue(value)
        progress_bar.setFormat(f"{value} / {maximum}")
        progress_bar.setTextVisible(True)

    @staticmethod
    def _set_fraction(progress_bar: QProgressBar, fraction: float) -> None:
        value = max(0, min(1000, int(round(float(fraction) * 1000))))
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(value)
        progress_bar.setFormat("%p%")
        progress_bar.setTextVisible(True)

    def _request_cancel(self) -> None:
        self.set_cancelling()
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


__all__ = ["HfTransferPanel"]
