from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class InferenceReviewBar(QFrame):
    """Shared footer used by every annotation panel for inference and review."""

    runRequested = pyqtSignal()
    acceptRequested = pyqtSignal()
    rejectRequested = pyqtSignal()
    acceptAllRequested = pyqtSignal()
    rejectAllRequested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inferenceReviewBar")
        self.setProperty("class", "inference_review_bar")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(4)

        self.status_label = QLabel("", self)
        self.status_label.setObjectName("inferencePredictionStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        self.run_button = QPushButton("Run Inference…", self)
        self.run_button.setObjectName("runInferenceButton")
        self.accept_button = QPushButton("Accept", self)
        self.accept_button.setObjectName("acceptPredictionButton")
        self.reject_button = QPushButton("Reject", self)
        self.reject_button.setObjectName("rejectPredictionButton")
        self.accept_all_button = QPushButton("Accept All", self)
        self.accept_all_button.setObjectName("acceptAllPredictionsButton")
        self.reject_all_button = QPushButton("Reject All", self)
        self.reject_all_button.setObjectName("rejectAllPredictionsButton")

        button_row.addWidget(self.run_button)
        button_row.addStretch(1)
        button_row.addWidget(self.accept_button)
        button_row.addWidget(self.reject_button)
        button_row.addWidget(self.accept_all_button)
        button_row.addWidget(self.reject_all_button)
        layout.addLayout(button_row)

        self.run_button.clicked.connect(self.runRequested.emit)
        self.accept_button.clicked.connect(self.acceptRequested.emit)
        self.reject_button.clicked.connect(self.rejectRequested.emit)
        self.accept_all_button.clicked.connect(self.acceptAllRequested.emit)
        self.reject_all_button.clicked.connect(self.rejectAllRequested.emit)
        self.set_review_actions_visible(False)

    def set_review_actions_visible(
        self,
        visible: bool,
        *,
        allow_selected: bool = True,
        allow_bulk: bool = False,
    ) -> None:
        visible = bool(visible)
        self.accept_button.setVisible(visible and allow_selected)
        self.reject_button.setVisible(visible and allow_selected)
        self.accept_all_button.setVisible(visible and allow_bulk)
        self.reject_all_button.setVisible(visible and allow_bulk)

    def set_status(self, text: str = "") -> None:
        text = str(text or "").strip()
        self.status_label.setText(text)
        self.status_label.setVisible(bool(text))

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not bool(running))
        self.run_button.setText("Running Inference…" if running else "Run Inference…")


__all__ = ["InferenceReviewBar"]
