"""Dialogs for read-only localization head evaluation."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from localization_evaluation import (
    DEFAULT_TOLERANCES_MS, eligible_segments, observed_labels,
)


def tolerance_label(milliseconds: int) -> str:
    seconds = milliseconds / 1000
    return str(int(seconds)) if seconds.is_integer() else f"{seconds:.1f}"


class LocalizationEvaluationDialog(QDialog):
    """Choose two heads, sample scope, label mapping, and AP tolerances."""

    def __init__(self, samples, schema, selected_sample_id, current_head, parent=None):
        super().__init__(parent)
        self.samples = samples
        self.schema = schema if isinstance(schema, dict) else {}
        self.selected_sample_id = str(selected_sample_id or "")
        self.setWindowTitle("Evaluate Localization")
        self.resize(590, 560)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)
        self.scope_combo = QComboBox(self)
        self.scope_combo.addItem("Whole project", "project")
        self.scope_combo.addItem("Selected sample", "selected")
        self.scope_combo.model().item(1).setEnabled(bool(self.selected_sample_id))
        form.addRow("Evaluate:", self.scope_combo)

        heads = list(dict.fromkeys([
            *[str(head) for head in self.schema if str(head).strip()],
            *[
                str(event.get("head"))
                for sample in self.samples if isinstance(sample, dict)
                for event in (sample.get("events") or []) if isinstance(event, dict)
                and str(event.get("head") or "").strip()
            ],
        ]))
        self.truth_combo = QComboBox(self)
        self.prediction_combo = QComboBox(self)
        for head in heads:
            self.truth_combo.addItem(head, head)
            self.prediction_combo.addItem(head, head)
        if current_head in heads:
            self.prediction_combo.setCurrentIndex(heads.index(current_head))
            for index, head in enumerate(heads):
                if head != current_head:
                    self.truth_combo.setCurrentIndex(index)
                    break
        elif len(heads) > 1:
            self.prediction_combo.setCurrentIndex(1)
        form.addRow("Ground truth head:", self.truth_combo)
        form.addRow("Prediction head:", self.prediction_combo)

        layout.addWidget(QLabel("Prediction class mapping", self))
        self.mapping_table = QTableWidget(0, 2, self)
        self.mapping_table.setHorizontalHeaderLabels(["Prediction label", "Ground truth label"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.mapping_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.mapping_table, 1)

        layout.addWidget(QLabel("AP tolerances (seconds)", self))
        self.tolerance_list = QListWidget(self)
        self.tolerance_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tolerance_list.setMaximumHeight(110)
        layout.addWidget(self.tolerance_list)
        row = QHBoxLayout()
        self.tolerance_spin = QDoubleSpinBox(self)
        self.tolerance_spin.setRange(0.0, 60.0)
        self.tolerance_spin.setDecimals(1)
        self.tolerance_spin.setSingleStep(0.1)
        self.tolerance_spin.setSuffix(" s")
        self.tolerance_spin.setValue(5.0)
        self.add_tolerance_button = QPushButton("Add tolerance", self)
        self.remove_tolerance_button = QPushButton("Remove selected", self)
        row.addWidget(self.tolerance_spin)
        row.addWidget(self.add_tolerance_button)
        row.addWidget(self.remove_tolerance_button)
        layout.addLayout(row)
        self.details_label = QLabel(self)
        self.details_label.setWordWrap(True)
        layout.addWidget(self.details_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Evaluate")
        layout.addWidget(self.buttons)
        self._mapping_error = False
        for milliseconds in DEFAULT_TOLERANCES_MS:
            self._insert_tolerance(milliseconds)

        self.scope_combo.currentIndexChanged.connect(self._refresh_mapping)
        self.truth_combo.currentIndexChanged.connect(self._refresh_mapping)
        self.prediction_combo.currentIndexChanged.connect(self._refresh_mapping)
        self.add_tolerance_button.clicked.connect(self._add_tolerance)
        self.remove_tolerance_button.clicked.connect(self._remove_tolerances)
        self.buttons.accepted.connect(self._accept_if_valid)
        self.buttons.rejected.connect(self.reject)
        self._refresh_mapping()

    def _insert_tolerance(self, milliseconds):
        values = set(self.tolerances_ms())
        values.add(int(milliseconds))
        self.tolerance_list.clear()
        for value in sorted(values):
            item = QListWidgetItem(f"AP@{tolerance_label(value)} s", self.tolerance_list)
            item.setData(Qt.ItemDataRole.UserRole, value)
        self._validate()

    def _add_tolerance(self):
        self._insert_tolerance(round(self.tolerance_spin.value() * 1000))

    def _remove_tolerances(self):
        for item in self.tolerance_list.selectedItems():
            self.tolerance_list.takeItem(self.tolerance_list.row(item))
        self._validate()

    def tolerances_ms(self) -> tuple[int, ...]:
        return tuple(
            int(self.tolerance_list.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.tolerance_list.count())
        )

    def mapping(self) -> dict[str, str | None]:
        return {
            self.mapping_table.item(row, 0).text(): self.mapping_table.cellWidget(row, 1).currentData()
            for row in range(self.mapping_table.rowCount())
        }

    def _head_labels(self, head: str) -> tuple[str, ...]:
        definition = self.schema.get(head)
        labels = definition.get("labels", []) if isinstance(definition, dict) else []
        if not isinstance(labels, (list, tuple)):
            return ()
        return tuple(str(label).strip() for label in labels if str(label).strip())

    def _refresh_mapping(self, *_args):
        old_mapping = self.mapping()
        truth_head = str(self.truth_combo.currentData() or "")
        prediction_head = str(self.prediction_combo.currentData() or "")
        try:
            segments, skipped = eligible_segments(
                self.samples, str(self.scope_combo.currentData()),
                self.selected_sample_id, (truth_head, prediction_head),
            )
        except ValueError as exc:
            self._mapping_error = True
            self.details_label.setText(str(exc))
            self.mapping_table.setRowCount(0)
            self._validate()
            return
        self._mapping_error = False
        truth_labels = set(self._head_labels(truth_head))
        truth_labels |= observed_labels(segments, truth_head)
        prediction_labels = sorted(observed_labels(segments, prediction_head))
        self.mapping_table.setRowCount(len(prediction_labels))
        for row, label in enumerate(prediction_labels):
            self.mapping_table.setItem(row, 0, QTableWidgetItem(label))
            combo = QComboBox(self.mapping_table)
            combo.addItem("Choose label…", None)
            for truth_label in sorted(truth_labels):
                combo.addItem(truth_label, truth_label)
            selected = old_mapping.get(label)
            if selected not in truth_labels and label in truth_labels:
                selected = label
            if selected in truth_labels:
                combo.setCurrentIndex(combo.findData(selected))
            combo.currentIndexChanged.connect(self._validate)
            self.mapping_table.setCellWidget(row, 1, combo)
        self.details_label.setText(
            f"{len(segments)} eligible segment(s); {skipped} sample(s) skipped by annotation status."
        )
        self._validate()

    def _validate(self, *_args):
        valid = (
            self.truth_combo.currentData()
            and self.prediction_combo.currentData()
            and self.truth_combo.currentData() != self.prediction_combo.currentData()
            and not self._mapping_error
            and bool(self.tolerances_ms())
            and all(self.mapping().values())
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(valid))

    def _accept_if_valid(self):
        self._validate()
        if self.buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled():
            self.accept()

    def options(self) -> dict:
        truth_head = str(self.truth_combo.currentData())
        return {
            "scope": str(self.scope_combo.currentData()),
            "selected_sample_id": self.selected_sample_id,
            "truth_head": truth_head,
            "prediction_head": str(self.prediction_combo.currentData()),
            "mapping": self.mapping(),
            "tolerances_ms": self.tolerances_ms(),
            "truth_labels": self._head_labels(truth_head),
        }


class LocalizationEvaluationResultsDialog(QDialog):
    """Show the read-only AP report returned by the evaluator."""

    def __init__(self, report: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Localization Evaluation")
        self.resize(780, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            f"{report['sample_count']} sample(s), {report['segment_count']} segment(s); "
            f"{report['truth_count']} ground-truth event(s), "
            f"{report['prediction_count']} prediction event(s); "
            f"{report['skipped_samples']} sample(s) skipped by annotation status.",
            self,
        ))
        layout.addWidget(QLabel(
            "The overall row shows mAP across classes; each class row shows AP. "
            "N/A classes have no ground-truth events and are excluded from mAP.",
            self,
        ))
        tolerances = report["tolerances_ms"]
        table = QTableWidget(len(report["classes"]) + 1, len(tolerances) + 3, self)
        table.setHorizontalHeaderLabels([
            "Class", "Tight mAP", "Loose mAP",
            *[f"AP@{tolerance_label(value)} s" for value in tolerances],
        ])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        rows = [("Overall", report["overall"]), *report["classes"].items()]
        for row, (label, values) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(label))
            scores = (
                [values["tight"], values["loose"]]
                + [values["ap"][tolerance] for tolerance in tolerances]
                if values is not None else [None] * (len(tolerances) + 2)
            )
            for column, score in enumerate(scores, 1):
                table.setItem(
                    row, column,
                    QTableWidgetItem("N/A" if score is None else f"{score * 100:.2f}%"),
                )
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
