#!/usr/bin/env python3
from pathlib import Path
import sys

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

def walk_tree(root: Path, prefix: str = "") -> int:
    total_lines = 0

    entries = sorted(
        [p for p in root.iterdir() if p.name not in IGNORE_DIRS],
        key=lambda p: (p.is_file(), p.name.lower())
    )

    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        next_prefix = prefix + ("    " if is_last else "│   ")

        if entry.is_dir():
            print(f"{prefix}{connector}{entry.name}/")
            total_lines += walk_tree(entry, next_prefix)

        elif entry.suffix == ".py":
            n = count_lines(entry)
            label = f"{n} lines" if n >= 0 else "unreadable"
            print(f"{prefix}{connector}{entry.name} [{label}]")

            if n >= 0:
                total_lines += n

    return total_lines

def main():
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    root = root.resolve()

    print(f"{root.name}/")
    total = walk_tree(root)
    print(f"\nTotal Python lines: {total}")

if __name__ == "__main__":
    main()