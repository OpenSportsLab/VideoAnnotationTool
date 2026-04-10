#!/usr/bin/env python3
import argparse
from pathlib import Path

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".idea",
    ".vscode",
    "build",
    "dist",
    "test_data",
}


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except Exception:
        return -1


def compute_dir_totals(root: Path, totals: dict[Path, int]) -> int:
    total_lines = 0

    entries = sorted(
        [p for p in root.iterdir() if p.name not in IGNORE_DIRS],
        key=lambda p: (p.is_file(), p.name.lower()),
    )

    for entry in entries:
        if entry.is_dir():
            total_lines += compute_dir_totals(entry, totals)
        elif entry.suffix == ".py":
            n = count_lines(entry)
            if n >= 0:
                total_lines += n

    totals[root] = total_lines
    return total_lines


def walk_tree(root: Path, totals: dict[Path, int], prefix: str = "") -> None:
    entries = sorted(
        [p for p in root.iterdir() if p.name not in IGNORE_DIRS],
        key=lambda p: (p.is_file(), p.name.lower()),
    )

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        next_prefix = prefix + ("    " if is_last else "│   ")

        if entry.is_dir():
            print(f"{prefix}{connector}{entry.name}/ [{totals.get(entry, 0)} lines]")
            walk_tree(entry, totals, next_prefix)
        elif entry.suffix == ".py":
            n = count_lines(entry)
            label = f"{n} lines" if n >= 0 else "unreadable"
            print(f"{prefix}{connector}{entry.name} [{label}]")


def main():
    parser = argparse.ArgumentParser(
        description="Count Python lines for a directory tree."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to analyze. Defaults to the current directory.",
    )
    args = parser.parse_args()

    root = Path(args.path)
    root = root.resolve()

    totals: dict[Path, int] = {}
    grand_total = compute_dir_totals(root, totals)

    print(f"{root.name}/ [{grand_total} lines]")
    walk_tree(root, totals)
    print(f"\nTotal Python lines: {grand_total}")


if __name__ == "__main__":
    main()