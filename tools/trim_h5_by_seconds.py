#!/usr/bin/env python3
"""Create an HDF5 copy containing a timestamped time window.

Example:
    python tools/trim_h5_by_seconds.py \
        --input test_data/FIFA_data/128083/live_joints.h5 \
        --output test_data/FIFA_data/128083/live_joints_first_10s.h5 \
        --start-seconds 0 \
        --duration-seconds 10
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

import h5py
import numpy as np


DEFAULT_CHUNK_SIZE = 250_000


def _parse_timestamp(value: Any, index: int) -> datetime:
    """Parse one HDF5 timestamp and normalize it to UTC."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if isinstance(value, np.bytes_):
        value = bytes(value).decode("utf-8", errors="strict")

    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"malformed timestamp_utc at row {index}: {value!r}") from error

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iter_timestamp_chunks(
    timestamp_dataset: h5py.Dataset, chunk_size: int
) -> Iterator[tuple[int, list[datetime]]]:
    """Yield parsed timestamp chunks without loading the entire dataset."""
    if timestamp_dataset.ndim != 1:
        raise ValueError("timestamp_utc must be a one-dimensional dataset")

    for start in range(0, len(timestamp_dataset), chunk_size):
        values = timestamp_dataset[start : start + chunk_size]
        yield start, [_parse_timestamp(value, start + offset) for offset, value in enumerate(values)]


def _build_keep_mask(
    timestamp_dataset: h5py.Dataset,
    start_seconds: float,
    duration_seconds: float,
    chunk_size: int,
) -> np.ndarray:
    """Return a row mask for a window relative to the earliest timestamp."""
    minimum: datetime | None = None
    for _, timestamps in _iter_timestamp_chunks(timestamp_dataset, chunk_size):
        chunk_minimum = min(timestamps) if timestamps else None
        if chunk_minimum is not None and (minimum is None or chunk_minimum < minimum):
            minimum = chunk_minimum

    if minimum is None:
        return np.zeros(len(timestamp_dataset), dtype=bool)

    window_start = minimum + timedelta(seconds=start_seconds)
    window_end = window_start + timedelta(seconds=duration_seconds)
    keep_mask = np.zeros(len(timestamp_dataset), dtype=bool)
    for start, timestamps in _iter_timestamp_chunks(timestamp_dataset, chunk_size):
        keep_mask[start : start + len(timestamps)] = [
            window_start <= timestamp < window_end for timestamp in timestamps
        ]
    return keep_mask


def _copy_attributes(source: h5py.Group | h5py.Dataset, destination: h5py.Group | h5py.Dataset) -> None:
    for key, value in source.attrs.items():
        destination.attrs[key] = value


def _copy_group(
    source: h5py.Group,
    destination: h5py.Group,
    keep_mask: np.ndarray,
    row_count: int,
    chunk_size: int,
) -> None:
    """Copy a group recursively, filtering datasets aligned to timestamp rows."""
    _copy_attributes(source, destination)
    for name, item in source.items():
        if isinstance(item, h5py.Group):
            child = destination.create_group(name)
            _copy_group(item, child, keep_mask, row_count, chunk_size)
            continue

        if not isinstance(item, h5py.Dataset):
            continue

        is_row_aligned = item.ndim >= 1 and item.shape[0] == row_count
        if not is_row_aligned:
            copied = destination.create_dataset(name, data=item[()])
            _copy_attributes(item, copied)
            continue

        retained_count = int(keep_mask.sum())
        output_shape = (retained_count,) + item.shape[1:]
        copied = destination.create_dataset(name, shape=output_shape, dtype=item.dtype)
        _copy_attributes(item, copied)

        write_start = 0
        for start in range(0, row_count, chunk_size):
            stop = min(start + chunk_size, row_count)
            selected = keep_mask[start:stop]
            if not selected.any():
                continue
            values = item[start:stop][selected]
            copied[write_start : write_start + len(values)] = values
            write_start += len(values)


def trim_h5_file(
    input_path: Path,
    output_path: Path,
    start_seconds: float,
    duration_seconds: float,
) -> int:
    """Trim one HDF5 file and return the number of retained rows."""
    input_path = input_path.resolve()
    output_path = output_path.resolve()
    if input_path == output_path:
        raise ValueError("input and output paths must be different")
    if start_seconds < 0:
        raise ValueError("start-seconds must be zero or greater")
    if duration_seconds <= 0:
        raise ValueError("duration-seconds must be greater than zero")

    with h5py.File(input_path, "r") as source:
        if "timestamp_utc" not in source:
            raise ValueError("missing required dataset: timestamp_utc")
        timestamp_dataset = source["timestamp_utc"]
        row_count = len(timestamp_dataset)
        keep_mask = _build_keep_mask(
            timestamp_dataset,
            start_seconds,
            duration_seconds,
            DEFAULT_CHUNK_SIZE,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with h5py.File(output_path, "w") as destination:
            _copy_group(source, destination, keep_mask, row_count, DEFAULT_CHUNK_SIZE)

    return int(keep_mask.sum())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="source HDF5 file")
    parser.add_argument("--output", required=True, type=Path, help="destination HDF5 file")
    parser.add_argument(
        "--start-seconds",
        required=True,
        type=float,
        help="offset from the file's earliest timestamp",
    )
    parser.add_argument(
        "--duration-seconds",
        required=True,
        type=float,
        help="window duration to retain",
    )
    args = parser.parse_args()

    try:
        retained_rows = trim_h5_file(
            args.input,
            args.output,
            args.start_seconds,
            args.duration_seconds,
        )
    except (OSError, ValueError, UnicodeError) as error:
        parser.error(str(error))

    print(f"Wrote {retained_rows} row(s) to {args.output}")


if __name__ == "__main__":
    main()
