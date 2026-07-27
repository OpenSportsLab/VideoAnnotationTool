#!/usr/bin/env python3
"""Print team IDs and names stored in one or more HDF5 files.

Usage:
    python tools/read_h5_team_info.py test_data/FIFA_data/133041/live_joints.h5
    python tools/read_h5_team_info.py --output teams.csv game1.h5 game2.h5
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any

import h5py


def _text(value: Any) -> str:
    """Convert HDF5 bytes/object values to printable text."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def read_team_info(path: Path) -> dict[str, Any]:
    """Read home/away team IDs and names from an HDF5 file."""
    with h5py.File(path, "r") as h5_file:
        required = {"home_name", "away_name"}
        missing = required - set(h5_file.keys())
        if missing:
            raise ValueError(f"missing dataset(s): {', '.join(sorted(missing))}")

        names = {
            "home": _text(h5_file["home_name"][0]),
            "away": _text(h5_file["away_name"][0]),
        }
        teams: dict[str, dict[str, str]] = {
            "home": {"id": "", "name": names["home"]},
            "away": {"id": "", "name": names["away"]},
        }

        # FIFA tracking files associate team_id with is_home (1=home, 0=away).
        if {"team_id", "is_home"}.issubset(h5_file.keys()):
            team_ids = h5_file["team_id"]
            home_flags = h5_file["is_home"]
            for start in range(0, len(team_ids), 250_000):
                stop = min(start + 250_000, len(team_ids))
                for team_id, is_home in zip(
                    team_ids[start:stop], home_flags[start:stop]
                ):
                    team_id_text = _text(team_id).strip()
                    side = "home" if int(is_home) == 1 else "away" if int(is_home) == 0 else None
                    if side and team_id_text and not teams[side]["id"]:
                        teams[side]["id"] = team_id_text
                if all(team["id"] for team in teams.values()):
                    break

        return {"file": str(path), "teams": teams}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="HDF5 files to inspect",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("team_info.csv"),
        help="CSV output path (default: team_info.csv)",
    )
    args = parser.parse_args()

    results = []
    for path in args.files:
        if path.suffix.lower() not in {".h5", ".hdf5"}:
            parser.error(f"{path}: expected an .h5 or .hdf5 file")
        try:
            results.append(read_team_info(path))
        except (OSError, KeyError, ValueError) as error:
            parser.error(f"{path}: {error}")

    fieldnames = [
        "file",
        "home_team_id",
        "home_team_name",
        "away_team_id",
        "away_team_name",
    ]
    with args.output.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "file": result["file"],
                    "home_team_id": result["teams"]["home"]["id"],
                    "home_team_name": result["teams"]["home"]["name"],
                    "away_team_id": result["teams"]["away"]["id"],
                    "away_team_name": result["teams"]["away"]["name"],
                }
            )

    print(f"Wrote {len(results)} result(s) to {args.output}")


if __name__ == "__main__":
    main()
