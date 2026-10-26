"""One-time document relocation. Original report bytes stay unchanged."""
import ast
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[3]
AUDIT = Path(__file__).resolve().parent


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def save_before(path, area):
    destination = AUDIT / area / path.relative_to(ROOT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(path, destination)


def main():
    if (AUDIT / "operations.json").exists():
        raise SystemExit("Migration already applied; inspect operations.json.")
    documents = json.loads((ROOT / "docs/catalog.json").read_text())["documents"]
    moves = []
    for row in documents:
        source = ROOT / row["original_path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == row["migration_sha256"]
        moves.append({"old": row["original_path"], "new": row["path"], "kind": "document"})
        if row.get("reader"):
            moves.append({"old": row["original_reader"], "new": row["reader"], "kind": "document_reader"})
    for row in moves:
        assert (ROOT / row["old"]).is_file(), row
        assert not (ROOT / row["new"]).exists(), row
    # Capture only symlinks that directly point to a document being moved.
    lookup = {str(ROOT / r["old"]): ROOT / r["new"] for r in moves}
    symlinks = []
    for folder in ("docs", "research", "experiments"):
        for parent, dirs, files in os.walk(ROOT / folder):
            dirs[:] = [d for d in dirs if d not in ("maintenance", "build", "__pycache__")]
            for name in dirs + files:
                path = Path(parent) / name
                if path.is_symlink():
                    target = os.path.abspath(path.parent / os.readlink(path))
                    if target in lookup:
                        symlinks.append({"path": str(path.relative_to(ROOT)), "old": os.readlink(path),
                                         "new": os.path.relpath(lookup[target], path.parent)})
    for row in moves:
        source, destination = ROOT / row["old"], ROOT / row["new"]
        if row["kind"] == "document_reader":
            save_before(source, "before_readers")
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    for row in symlinks:
        path = ROOT / row["path"]
        path.unlink()
        path.symlink_to(row["new"])
    mapping_path = ROOT / "results/path_map.json"
    mapping = json.loads(mapping_path.read_text())
    assert not set(r["old"] for r in moves) & set(r["old"] for r in mapping["mappings"])
    mapping["mappings"] += moves
    mapping["mappings"].sort(key=lambda r: r["old"])
    mapping_path.write_text(dump(mapping))
    stream = io.StringIO()
    writer = csv.DictWriter(stream, ["old", "new", "kind"], delimiter="\t", lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(mapping["mappings"])
    (ROOT / "results/path_map.tsv").write_text(stream.getvalue())
    layout = ROOT / "experiments/directory_layout.json"
    data = json.loads(layout.read_text())
    data["document_moves"] = moves
    layout.write_text(dump(data))
    paths = {row["old"]: row["new"] for row in moves}

    def update(value):
        if isinstance(value, dict):
            return {key: update(item) for key, item in value.items()}
        if isinstance(value, list):
            return [update(item) for item in value]
        return paths.get(value, value) if isinstance(value, str) else value

    catalog = ROOT / "experiments/pilot_catalog.json"
    catalog.write_text(dump(update(json.loads(catalog.read_text()))))
    changed = []
    # Update operational paths, while retaining embedded before_report snapshots.
    for source in sorted((ROOT / "scripts").rglob("*.py")):
        original = source.read_text()
        content = original
        for old, new in sorted(paths.items(), key=lambda pair: -len(pair[0])):
            content = re.sub(r"(?<![A-Za-z0-9_/])" + re.escape(old) + r"(?![A-Za-z0-9_])",
                             lambda _: new, content)
        if original == content:
            continue
        ast.parse(content)
        save_before(source, "before_code")
        source.write_text(content)
        changed.append(str(source.relative_to(ROOT)))
    (AUDIT / "operations.json").write_text(dump({"moves": moves, "symlinks": symlinks,
                                                "updated_scripts": changed, "status": "complete"}))
    print(dump({"moved_documents": len(documents), "moved_readers": len(moves) - len(documents),
                "updated_scripts": len(changed), "updated_symlinks": len(symlinks)}))


if __name__ == "__main__":
    main()
