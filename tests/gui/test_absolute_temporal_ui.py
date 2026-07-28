import pytest
from PyQt6.QtCore import Qt

from ui.dense_description import DenseTableModel
from ui.localization import _LocalizationTableModel


@pytest.mark.parametrize(
    "model_factory,event",
    [
        (
            _LocalizationTableModel,
            {"head": "action", "label": "pass", "position_ms": 1000},
        ),
        (
            DenseTableModel,
            {"lang": "en", "text": "caption", "position_ms": 1000},
        ),
    ],
)
def test_temporal_tables_display_full_utc_for_absolute_and_legacy_events(
    qtbot,
    model_factory,
    event,
):
    absolute = dict(
        event,
        position_ms=9999,
        timestamp_utc="2026-01-01T14:00:02.500000+02:00",
    )
    malformed = dict(event, position_ms=3000, timestamp_utc="bad-time")
    model = model_factory([absolute, event, malformed])
    model.set_timeline_origin("2026-01-01 12:00:00.000000")

    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == (
        "2026-01-01 12:00:02.500 UTC"
    )
    assert model.data(model.index(1, 0), Qt.ItemDataRole.DisplayRole) == (
        "2026-01-01 12:00:01.000 UTC"
    )
    assert model.data(model.index(2, 0), Qt.ItemDataRole.DisplayRole) == "00:03.000"


@pytest.mark.parametrize(
    "model_factory,event",
    [
        (
            _LocalizationTableModel,
            {"head": "action", "label": "pass", "position_ms": 1000},
        ),
        (
            DenseTableModel,
            {"lang": "en", "text": "caption", "position_ms": 1000},
        ),
    ],
)
def test_temporal_tables_edit_utc_and_keep_position_for_seeking(
    qtbot,
    model_factory,
    event,
):
    model = model_factory([event])
    model.set_timeline_origin("2026-01-01 12:00:00.000000")
    changed = []
    model.itemChanged.connect(lambda old, new: changed.append((old, new)))
    index = model.index(0, 0)

    assert model.setData(
        index,
        "2026-01-01T14:00:03.250000+02:00",
        Qt.ItemDataRole.EditRole,
    )
    updated = model.get_annotation_at(0)
    assert updated["timestamp_utc"] == "2026-01-01 12:00:03.250000"
    assert updated["position_ms"] == 3250
    assert len(changed) == 1

    assert not model.setData(index, "not-a-time", Qt.ItemDataRole.EditRole)
    assert model.get_annotation_at(0) == updated
    assert len(changed) == 1


def test_relative_table_time_edit_remains_supported(qtbot):
    model = DenseTableModel([{"position_ms": 1000, "lang": "en", "text": "caption"}])
    assert model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole) == "00:01.000"
    assert model.setData(model.index(0, 0), "00:02.500", Qt.ItemDataRole.EditRole)
    assert model.get_annotation_at(0)["position_ms"] == 2500
