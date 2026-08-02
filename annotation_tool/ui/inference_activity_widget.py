"""Non-modal status-bar progress UI for the active inference request."""

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton


class InferenceActivityWidget(QFrame):
    cancelRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary = ""
        self.setObjectName("inferenceActivityWidget")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 1, 2, 1)
        layout.setSpacing(6)

        self.label = QLabel("", self)
        self.label.setObjectName("inferenceActivityLabel")
        self.progress = QProgressBar(self)
        self.progress.setObjectName("inferenceActivityProgress")
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(130)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setObjectName("cancelInferenceButton")

        layout.addWidget(self.label, 1)
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel_button)
        self.cancel_button.clicked.connect(self._request_cancel)
        self.setVisible(False)

    def start(self, task: str, model_id: str, sample_count: int) -> None:
        task_name = str(task or "inference").replace("_", " ").title()
        target = "1 sample" if int(sample_count or 0) == 1 else f"{int(sample_count or 0)} samples"
        self._summary = f"{task_name} · {model_id} · {target}"
        self.label.setText(self._summary)
        self.progress.setRange(0, 0)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")
        self.setVisible(True)

    def update_progress(self, message: str, current: int, total: int) -> None:
        if str(message or "").strip():
            self.label.setText(f"{self._summary} · {str(message).strip()}")
        if int(total or 0) > 0:
            total = int(total)
            self.progress.setRange(0, total)
            self.progress.setValue(max(0, min(int(current or 0), total)))
        else:
            self.progress.setRange(0, 0)

    def finish(self) -> None:
        self.setVisible(False)
        self._summary = ""
        self.label.clear()
        self.progress.setRange(0, 0)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setText("Cancel")

    def _request_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancelling…")
        self.cancelRequested.emit()


__all__ = ["InferenceActivityWidget"]
