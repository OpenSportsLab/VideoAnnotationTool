import importlib.util
from pathlib import Path

import h5py
import numpy as np
import pytest

SCRIPT_PATH = Path(__file__).parents[1] / "tools" / "trim_h5_by_seconds.py"
MODULE_SPEC = importlib.util.spec_from_file_location("trim_h5_by_seconds", SCRIPT_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
TRIM_MODULE = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(TRIM_MODULE)
trim_h5_file = TRIM_MODULE.trim_h5_file


def _write_source(path: Path, timestamps: list[bytes]) -> None:
    with h5py.File(path, "w") as h5_file:
        h5_file.attrs["source"] = "fixture"
        h5_file.create_dataset("timestamp_utc", data=np.asarray(timestamps))
        values = h5_file.create_dataset("values", data=np.arange(len(timestamps)))
        values.attrs["unit"] = "index"
        h5_file.create_dataset("metadata", data=np.asarray([b"kept"]))


def test_trims_unsorted_rows_and_excludes_cutoff(tmp_path: Path):
    source = tmp_path / "source.h5"
    output = tmp_path / "nested" / "trimmed.h5"
    _write_source(
        source,
        [
            b"2026-01-01 00:00:03.000000",
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:01.500000",
            b"2026-01-01 00:00:02.000000",
        ],
    )

    assert trim_h5_file(source, output, 0, 2) == 2
    with h5py.File(output, "r") as h5_file:
        assert h5_file["values"][:].tolist() == [1, 2]
        assert h5_file["timestamp_utc"][:].tolist() == [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:01.500000",
        ]
        assert h5_file.attrs["source"] == "fixture"
        assert h5_file["values"].attrs["unit"] == "index"
        assert h5_file["metadata"][:].tolist() == [b"kept"]


def test_empty_result_is_supported(tmp_path: Path):
    source = tmp_path / "source.h5"
    output = tmp_path / "trimmed.h5"
    _write_source(source, [b"2026-01-01 00:00:10.000000"])

    # A positive duration always includes the earliest timestamp, but a file
    # with no rows must still produce valid empty row-aligned datasets.
    with h5py.File(source, "a") as h5_file:
        del h5_file["timestamp_utc"]
        h5_file.create_dataset("timestamp_utc", shape=(0,), dtype="S26")
        del h5_file["values"]
        h5_file.create_dataset("values", shape=(0,), dtype="i8")

    assert trim_h5_file(source, output, 0, 1) == 0
    with h5py.File(output, "r") as h5_file:
        assert h5_file["timestamp_utc"].shape == (0,)
        assert h5_file["values"].shape == (0,)


def test_supports_nonzero_start_offset(tmp_path: Path):
    source = tmp_path / "source.h5"
    output = tmp_path / "trimmed.h5"
    _write_source(
        source,
        [
            b"2026-01-01 00:00:00.000000",
            b"2026-01-01 00:00:01.000000",
            b"2026-01-01 00:00:02.000000",
            b"2026-01-01 00:00:03.000000",
        ],
    )

    assert trim_h5_file(source, output, 1, 2) == 2
    with h5py.File(output, "r") as h5_file:
        assert h5_file["values"][:].tolist() == [1, 2]


@pytest.mark.parametrize("start_seconds", [-1, -0.1])
def test_rejects_negative_start_offset(tmp_path: Path, start_seconds: float):
    source = tmp_path / "source.h5"
    _write_source(source, [b"2026-01-01 00:00:00.000000"])
    with pytest.raises(ValueError, match="start-seconds"):
        trim_h5_file(source, tmp_path / "output.h5", start_seconds, 1)


@pytest.mark.parametrize("duration_seconds", [0, -1])
def test_rejects_non_positive_duration(tmp_path: Path, duration_seconds: float):
    source = tmp_path / "source.h5"
    _write_source(source, [b"2026-01-01 00:00:00.000000"])
    with pytest.raises(ValueError, match="duration-seconds"):
        trim_h5_file(source, tmp_path / "output.h5", 0, duration_seconds)


def test_rejects_missing_timestamp_dataset(tmp_path: Path):
    source = tmp_path / "source.h5"
    with h5py.File(source, "w") as h5_file:
        h5_file.create_dataset("values", data=[1])
    with pytest.raises(ValueError, match="timestamp_utc"):
        trim_h5_file(source, tmp_path / "output.h5", 0, 1)


def test_rejects_malformed_timestamp(tmp_path: Path):
    source = tmp_path / "source.h5"
    _write_source(source, [b"not-a-timestamp"])
    with pytest.raises(ValueError, match="malformed timestamp_utc"):
        trim_h5_file(source, tmp_path / "output.h5", 0, 1)


def test_rejects_same_input_and_output(tmp_path: Path):
    source = tmp_path / "source.h5"
    _write_source(source, [b"2026-01-01 00:00:00.000000"])
    with pytest.raises(ValueError, match="different"):
        trim_h5_file(source, source, 0, 1)
