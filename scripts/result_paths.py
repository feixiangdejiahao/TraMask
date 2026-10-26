"""Resolve archived experiment paths after directory renaming.

Only addresses change. This module never rewrites experiment JSON or log content.
"""
import argparse
from functools import lru_cache
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def mappings():
    path = ROOT / "results/path_map.json"
    if not path.exists():
        return []
    rows = json.loads(path.read_text())["mappings"]
    return sorted(rows, key=lambda row: len(Path(row["old"]).parts), reverse=True)


def canonical_path(value):
    """Accept an absolute path or a path relative to the repository root."""
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        return path
    for row in mappings():
        if relative == row["old"] or relative.startswith(row["old"] + "/"):
            return ROOT / (row["new"] + relative[len(row["old"]):])
    return path


def relative_path(value):
    return canonical_path(value).relative_to(ROOT).as_posix()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", help="Archived or current paths.")
    args = parser.parse_args()
    for value in args.paths:
        print(canonical_path(value))
