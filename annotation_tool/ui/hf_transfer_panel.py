"""Presentation-only panel for the active Hugging Face dataset transfer."""

from __future__ import annotations

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
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("HfTransferPanel")
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

        primary_controls = QHBoxLayout()
        primary_controls.addStretch(1)
        self.play_stop_button = QPushButton("Download", self.progress_widget)
        self.play_stop_button.setObjectName("hfTransferPlayStopButton")
        self.play_stop_button.clicked.connect(self._request_play_stop)
        primary_controls.addWidget(self.play_stop_button)
        self.clear_button = QPushButton("Clear", self.progress_widget)
        self.clear_button.setObjectName("hfTransferClearButton")
        self.clear_button.clicked.connect(self.clearRequested.emit)
        primary_controls.addWidget(self.clear_button)
        progress_layout.addLayout(primary_controls)

        secondary_controls = QHBoxLayout()
        secondary_controls.addStretch(1)
        self.download_missing_button = QPushButton(
            "Queue missing samples", self.progress_widget
        )
        self.download_missing_button.setObjectName("hfTransferDownloadMissingButton")
        self.download_missing_button.clicked.connect(
            self.downloadMissingRequested.emit
        )
        secondary_controls.addWidget(self.download_missing_button)
        progress_layout.addLayout(secondary_controls)
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
        self.state_label.setText(
            operation or self._one_line(message) or "Hugging Face download in progress"
        )
        self._running = True
        self.summary_label.clear()
        self.progress_widget.setVisible(True)
        self.play_stop_button.setText("Stop download")
        self.play_stop_button.setEnabled(True)
        self.clear_button.setEnabled(True)

    def begin_dry_run(self, message: str) -> None:
        self.clear_summary()
        self.state_label.setText("Hugging Face dry run in progress")
        self.summary_label.setText(self._one_line(message) or "Inspecting files…")
        self._running = True
        self.play_stop_button.setText("Stop download")
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
        # Detailed queue state is rendered exclusively from controller snapshots.
        return

    def set_queue_entries(self, entries: object) -> None:
        """Render a controller-owned queue snapshot without mutating queue state."""
        queue_entries = [dict(entry) for entry in list(entries or [])]
        self.file_list.clear()
        completed = 0
        active_entry = None
        for entry in queue_entries:
            path = str(entry.get("path") or "file")
            status = str(entry.get("status") or "queued").lower()
            downloaded = max(0, int(entry.get("downloaded_bytes") or 0))
            total = max(0, int(entry.get("total_bytes") or 0))
            speed = max(0.0, float(entry.get("average_speed") or 0.0))
            speed_text = f"{_format_bytes(speed)}/s" if speed > 0 else "—"
            if status == "completed":
                status_text = "Completed"
                completed += 1
            elif status == "active":
                status_text = (
                    f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
                    if total
                    else f"{_format_bytes(downloaded)} downloaded"
                )
                if active_entry is None:
                    active_entry = entry
            elif status == "failed":
                status_text = "Failed"
            else:
                status_text = "Queued"
            item = QTreeWidgetItem([path, status_text, speed_text])
            item.setToolTip(0, path)
            self.file_list.addTopLevelItem(item)

        total_files = len(queue_entries)
        self.overall_label.setText(f"Files: {completed} / {total_files}")
        self._set_count_progress(
            self.overall_progress_bar,
            completed,
            max(1, total_files),
            f"{completed} / {total_files} files",
        )
        if active_entry is None:
            self.current_file_label.setText("No active download")
            self.current_file_label.setToolTip("")
            self._set_fraction(self.file_progress_bar, 0)
        else:
            path = str(active_entry.get("path") or "file")
            downloaded = max(0, int(active_entry.get("downloaded_bytes") or 0))
            total = max(0, int(active_entry.get("total_bytes") or 0))
            speed = max(0.0, float(active_entry.get("average_speed") or 0.0))
            detail = (
                f"{_format_bytes(downloaded)} / {_format_bytes(total)}"
                if total
                else f"{_format_bytes(downloaded)} downloaded"
            )
            speed_text = f"{_format_bytes(speed)}/s" if speed > 0 else "—"
            self.current_file_label.setText(f"{path}  ·  {detail}  ·  {speed_text}")
            self.current_file_label.setToolTip(path)
            self._set_fraction(
                self.file_progress_bar, downloaded / total if total else 0
            )

    def set_stopping(self) -> None:
        self.play_stop_button.setEnabled(False)
        self.play_stop_button.setText("Stopping…")

    def set_paused(self, message: str = "Downloads stopped") -> None:
        self._running = False
        self.state_label.setText(message)
        self.current_file_label.setText("No active download")
        self._set_fraction(self.file_progress_bar, 0)
        self.play_stop_button.setText("Download")
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
        self.play_stop_button.setText("Download")
        self.play_stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)

    def set_idle(self) -> None:
        """Show an idle queue without adding a transfer-completion summary."""
        self._running = False
        self.state_label.setText("No active download")
        self.summary_label.clear()
        self.set_queue_count(0)
        self.current_file_label.setText("No active download")
        self._set_fraction(self.file_progress_bar, 0)
        self.progress_widget.setVisible(True)
        self.play_stop_button.setText("Download")
        self.play_stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)

    def clear_summary(self) -> None:
        self.set_queue_entries([])
        self.state_label.setText("No recent Hugging Face transfer")
        self.summary_label.clear()
        self.progress_widget.setVisible(True)
        self.set_queue_count(0)
        self._running = False
        self.play_stop_button.setText("Download")
        self.play_stop_button.setEnabled(False)
        self.clear_button.setEnabled(True)

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
