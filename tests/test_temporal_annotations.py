import datetime

from utils import (
    annotation_at_position,
    project_temporal_annotations,
    temporal_annotation_identity,
)


def test_absolute_annotation_projects_against_each_runtime_origin_without_mutation():
    annotation = {
        "head": "action",
        "label": "pass",
        "timestamp_utc": "2026-01-01T12:00:05Z",
        "position_ms": 999999,
    }

    first = project_temporal_annotations(
        [annotation], datetime.datetime(2026, 1, 1, 12, 0, 0)
    )[0]
    earlier = project_temporal_annotations(
        [annotation], datetime.datetime(2026, 1, 1, 11, 59, 58)
    )[0]
    later = project_temporal_annotations(
        [annotation], datetime.datetime(2026, 1, 1, 12, 0, 10)
    )[0]

    assert first["position_ms"] == 5000
    assert earlier["position_ms"] == 7000
    assert later["position_ms"] == -5000
    assert annotation["position_ms"] == 999999
    assert annotation["timestamp_utc"] == "2026-01-01T12:00:05Z"


def test_relative_fallback_and_absolute_event_identity():
    relative = {"position_ms": 1250, "lang": "en", "text": "caption"}
    assert project_temporal_annotations([relative], None)[0]["position_ms"] == 1250

    moved = annotation_at_position(
        relative,
        2500,
        datetime.datetime(2026, 1, 1, 12, 0, 0),
    )
    assert moved["timestamp_utc"] == "2026-01-01 12:00:02.500000"

    same_instant = dict(moved, position_ms=7, timestamp_utc="2026-01-01T14:00:02.5+02:00")
    assert temporal_annotation_identity(moved, ("lang", "text")) == (
        temporal_annotation_identity(same_instant, ("lang", "text"))
    )
