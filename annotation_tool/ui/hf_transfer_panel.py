"""Presentation-only panel for the active Hugging Face dataset transfer."""

from __future__ import annotations

import re
from time import monotonic

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


class HfTransferPanel(QWidget):
    """Show file and byte progress without blocking annotation work."""

    stopRequested = pyqtSignal()
    playRequested = pyqtSignal()
    downloadMissingRequested = pyqtSignal()
    clearRequested = pyqtSignal()
    _PROGRESS_PATTERN = re.compile(r"\[(\d+)/(\d+)\]")
    _REFERENCED_FILES_PATTERN = re.compile(r"Downloading (\d+) referenced files")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HfTransferPanel")
        self._files: dict[str, dict] = {}
        self._active_files: dict[str, str] = {}
        self._expected_file_count = 0
        self._file_count_offset = 0
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        header = QHBoxLayout()
        self.state_label = QLabel("No recent Hugging Face transfer", self)
        self.state_label.setObjectName("hfTransferState")
        self.state_label.setWordWrap(True)
        header.addWidget(self.state_label, 1)
        layout.addLayout(header)

        self.queue_label = QLabel("", self)
        self.queue_label.setObjectName("hfTransferQueue")
        self.queue_label.setVisible(False)
        layout.addWidget(self.queue_label)

        self.progress_widget = QWidget(self)
        progress_layout = QVBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(6)

        self.overall_label = QLabel("Files: discovering…", self.progress_widget)
        progress_layout.addWidget(self.overall_label)
        self.overall_progress_bar = self._create_progress_bar(
            "hfTransferOverallProgress", "Hugging Face downloaded file count"
        )
        progress_layout.addWidget(self.overall_progress_bar)

        self.current_file_label = QLabel("Waiting for the first file…", self.progress_widget)
        self.current_file_label.setObjectName("hfTransferCurrentFile")
        self.current_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        progress_layout.addWidget(self.current_file_label)
        self.file_progress_bar = self._create_progress_bar(
            "hfTransferFileProgress", "Hugging Face current file byte progress"
        )
        progress_layout.addWidget(self.file_progress_bar)

        self.file_list = QTreeWidget(self.progress_widget)
        self.file_list.setObjectName("hfTransferFileList")
        self.file_list.setHeaderLabels(["File", "Status", "Average speed"])
        self.file_list.setRootIsDecorated(False)
        self.file_list.setAlternatingRowColors(False)
        self.file_list.setMaximumHeight(150)
        self.file_list.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_list.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_list.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        progress_layout.addWidget(self.file_list)

        controls = QHBoxLayout()
        controls.addStretch(1)
        self.play_stop_button = QPushButton("Play", self.progress_widget)
        self.play_stop_button.setObjectName("hfTransferPlayStopButton")
        self.play_stop_button.clicked.connect(self._request_play_stop)
        controls.addWidget(self.play_stop_button)
        self.download_missing_button = QPushButton(
            "Download Missing Samples", self.progress_widget
        )
        self.download_missing_button.setObjectName("hfTransferDownloadMissingButton")
        self.download_missing_button.clicked.connect(
            self.downloadMissingRequested.emit
        )
        controls.addWidget(self.download_missing_button)
        self.clear_button = QPushButton("Clear", self.progress_widget)
        self.clear_button.setObjectName("hfTransferClearButton")
        self.clear_button.clicked.connect(self.clearRequested.emit)
        controls.addWidget(self.clear_button)
        progress_layout.addLayout(controls)
        layout.addWidget(self.progress_widget)

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
        progress_bar.setRange(0, 1)
        progress_bar.setValue(0)
        progress_bar.setTextVisible(True)
        return progress_bar

    def begin(
        self,
        message: str,
        *,
        operation: str = "",
        preserve_files: bool = False,
    ) -> None:
        if not preserve_files:
            self._files.clear()
            self._expected_file_count = 0
            self.file_list.clear()
        self._active_files = {
            record["item"].text(0): key
            for key, record in self._files.items()
            if not record["complete"]
        }
        self._file_count_offset = sum(
            bool(record["complete"]) for record in self._files.values()
        )
        self.state_label.setText(
            operation or self._one_line(message) or "Hugging Face download in progress"
        )
        self._running = True
        self._update_file_count()
        self.current_file_label.setText("Waiting for the first file…")
        self.current_file_label.setToolTip("")
        self._set_fraction(self.file_progress_bar, 0)
        self.summary_label.clear()
        self.progress_widget.setVisible(True)
        self.play_stop_button.setText("Stop")
        self.play_stop_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def begin_dry_run(self, message: str) -> None:
        self.clear_summary()
        self.state_label.setText("Hugging Face dry run in progress")
        self.summary_label.setText(self._one_line(message) or "Inspecting files…")
        self._running = True
        self.play_stop_button.setText("Stop")
        self.play_stop_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def set_dry_run_progress(self, message: str) -> None:
        text = self._one_line(message)
        if text:
            self.summary_label.setText(text)

    def set_queue_count(self, count: int) -> None:
        queued = max(0, int(count))
        self.queue_label.setText(
            f"{queued} download{'s' if queued != 1 else ''} queued"
        )
        self.queue_label.setVisible(queued > 0)
        if not self._running:
            self.play_stop_button.setEnabled(queued > 0)

    def set_stage_progress(self, message: str) -> None:
        text = self._one_line(message)
        if not text:
            return
        referenced_match = self._REFERENCED_FILES_PATTERN.search(text)
        if referenced_match:
            self._expected_file_count = max(
                self._expected_file_count,
                len(self._files) + int(referenced_match.group(1)),
            )
        matches = [
            (int(current), int(total))
            for current, total in self._PROGRESS_PATTERN.findall(text)
            if int(total) > 0
        ]
        if matches and "download" in text.lower():
            _, file_total = matches[-1]
            self._expected_file_count = max(
                self._expected_file_count,
                self._file_count_offset + file_total,
            )
        self._update_file_count()

    def plan_files(self, filenames: list[str]) -> None:
        for filename in filenames or []:
            path = str(filename or "").strip()
            if not path or path in self._active_files:
                continue
            record_key, _record = self._add_file_record(path, "Queued")
            self._active_files[path] = record_key
        self._expected_file_count = max(self._expected_file_count, len(self._files))
        self._update_file_count()

    def set_file_progress(
        self,
        filename: str,
        downloaded_bytes: int,
        total_bytes: int,
        *,
        now: float | None = None,
    ) -> None:
        downloaded = max(0, int(downloaded_bytes or 0))
        total = max(0, int(total_bytes or 0))
        path = str(filename or "file")
        timestamp = monotonic() if now is None else float(now)
        record_key = self._pending_record_key(path)
        record = self._files.get(record_key) if record_key is not None else None
        if record is None:
            record_key, record = self._add_file_record(path, "Queued")
            self._active_files[path] = record_key
            self._expected_file_count = max(self._expected_file_count, len(self._files))

        if record["start_time"] is None:
            record["start_time"] = timestamp
            record["start_bytes"] = downloaded
        elapsed = timestamp - float(record["start_time"])
        transferred = max(0, downloaded - int(record["start_bytes"]))
        if elapsed > 0 and transferred > 0:
            record["speed"] = transferred / elapsed
        record["last_bytes"] = downloaded

        speed = float(record["speed"])
        speed_text = f"{_format_bytes(speed)}/s" if speed > 0 else "—"
        if total:
            detail = f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
            self._set_fraction(self.file_progress_bar, downloaded / total)
        else:
            detail = f"{_format_bytes(downloaded)} downloaded"
            self._set_fraction(self.file_progress_bar, 0)
        complete = bool(total and downloaded >= total)
        record["complete"] = complete
        record["item"].setText(
            1, "Completed" if complete else f"Running · {detail}"
        )
        record["item"].setText(2, speed_text)
        self.current_file_label.setText(f"{path}  ·  {detail}  ·  {speed_text}")
        self.current_file_label.setToolTip(path)
        self.file_list.scrollToItem(record["item"])
        self._update_file_count()

    def set_file_completed(self, filename: str) -> None:
        path = str(filename or "file")
        record_key = self._pending_record_key(path)
        record = self._files.get(record_key) if record_key is not None else None
        if record is None:
            record_key, record = self._add_file_record(path, "Completed")
            self._active_files[path] = record_key
        record["complete"] = True
        record["item"].setText(1, "Completed")
        self._expected_file_count = max(self._expected_file_count, len(self._files))
        self._update_file_count()

    def _add_file_record(self, path: str, status: str) -> tuple[str, dict]:
        item = QTreeWidgetItem([path, status, "—"])
        item.setToolTip(0, path)
        self.file_list.addTopLevelItem(item)
        record = {
            "item": item,
            "start_time": None,
            "start_bytes": 0,
            "last_bytes": 0,
            "speed": 0.0,
            "complete": status == "Completed",
        }
        record_key = path
        suffix = 2
        while record_key in self._files:
            record_key = f"{path}#{suffix}"
            suffix += 1
        self._files[record_key] = record
        return record_key, record

    def _pending_record_key(self, path: str) -> str | None:
        record_key = self._active_files.get(path)
        if record_key is not None:
            return record_key
        normalized = path.replace("\\", "/")
        for planned_path, candidate_key in self._active_files.items():
            planned = planned_path.replace("\\", "/")
            if normalized.endswith(f"/{planned}"):
                self._active_files[path] = candidate_key
                return candidate_key
        return None

    def set_stopping(self) -> None:
        self.play_stop_button.setEnabled(False)
        self.play_stop_button.setText("Stopping…")

    def set_paused(self, message: str = "Downloads stopped") -> None:
        self._running = False
        self.state_label.setText(message)
        for record in self._files.values():
            if not record["complete"] and record["item"].text(1).startswith("Running"):
                record["item"].setText(1, "Queued")
        self.current_file_label.setText("No active download")
        self._set_fraction(self.file_progress_bar, 0)
        self.play_stop_button.setText("Play")
        self.play_stop_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def set_terminal(self, state: str, summary: str) -> None:
        self._running = False
        self.state_label.setText(state)
        self.summary_label.setText(str(summary or ""))
        self.set_queue_count(0)
        self.current_file_label.setText("No active download")
        self._set_fraction(self.file_progress_bar, 0)
        self.progress_widget.setVisible(True)
        self.play_stop_button.setText("Play")
        self.play_stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)

    def clear_summary(self) -> None:
        self._files.clear()
        self._active_files.clear()
        self._expected_file_count = 0
        self._file_count_offset = 0
        self.file_list.clear()
        self.state_label.setText("No recent Hugging Face transfer")
        self.summary_label.clear()
        self.overall_label.setText("Files: 0 / 0")
        self._set_count_progress(self.overall_progress_bar, 0, 1, "0 / 0 files")
        self.current_file_label.setText("No active download")
        self._set_fraction(self.file_progress_bar, 0)
        self.progress_widget.setVisible(True)
        self.set_queue_count(0)
        self._running = False
        self.play_stop_button.setText("Play")
        self.play_stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)

    def clear_files(self) -> None:
        """Clear displayed file history without changing queue/run state."""
        self._files.clear()
        self._active_files.clear()
        self._expected_file_count = 0
        self._file_count_offset = 0
        self.file_list.clear()
        self.summary_label.clear()
        self.overall_label.setText("Files: 0 / 0")
        self._set_count_progress(self.overall_progress_bar, 0, 1, "0 / 0 files")
        self.current_file_label.setText(
            "Waiting for the first file…" if self._running else "No active download"
        )
        self._set_fraction(self.file_progress_bar, 0)

    def _update_file_count(self) -> None:
        completed = sum(bool(record["complete"]) for record in self._files.values())
        total = max(self._expected_file_count, len(self._files), 1)
        self.overall_label.setText(
            f"Files: {completed} / {total}" if self._files or self._expected_file_count else "Files: discovering…"
        )
        self._set_count_progress(
            self.overall_progress_bar,
            completed,
            total,
            f"{completed} / {total} files",
        )

    @staticmethod
    def _one_line(message: str) -> str:
        return " ".join(str(message or "").splitlines()).strip()

    @staticmethod
    def _set_count_progress(
        progress_bar: QProgressBar,
        current: int,
        total: int,
        text: str | None = None,
    ) -> None:
        maximum = max(1, int(total))
        value = min(max(0, int(current)), maximum)
        progress_bar.setRange(0, maximum)
        progress_bar.setValue(value)
        progress_bar.setFormat(text or f"{value} / {maximum}")
        progress_bar.setTextVisible(True)

    @staticmethod
    def _set_fraction(progress_bar: QProgressBar, fraction: float) -> None:
        value = max(0, min(1000, int(round(float(fraction) * 1000))))
        progress_bar.setRange(0, 1000)
        progress_bar.setValue(value)
        progress_bar.setFormat("%p%")
        progress_bar.setTextVisible(True)

    def _request_play_stop(self) -> None:
        if self._running:
            self.set_stopping()
            self.stopRequested.emit()
            return
        self.playRequested.emit()


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
