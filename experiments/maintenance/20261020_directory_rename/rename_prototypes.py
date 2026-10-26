"""One-time extension of the directory migration: rename historical prototypes."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
AUDIT = Path(__file__).resolve().parent
PACKAGES = {
    "assertion_instances": "helper_assertion_instances_v01",
    "assertion_instances_v2": "helper_assertion_instances_v02",
    "assertion_windows": "assertion_window_generation",
    "edit_square": "test_edit_square_generation",
    "generic_v2": "test_edit_analogy_v02",
    "generic_v21": "test_edit_analogy_allow_erasing_v02_01",
    "generic_v3": "statement_aligned_test_analogy_v03",
    "generic_v4": "balanced_literal_test_analogy_v04",
    "generic_v5": "unified_view_test_analogy_v05",
    "observation_priority": "observation_guided_test_analogy",
    "oracle_symbolic": "oracle_value_analysis",
    "relation_frontier_demo": "program_relation_search_demo",
    "semantic_transport": "test_action_and_oracle_transfer",
    "notes": "research_notes",
}


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def rewrite_modules(text):
    for old, new in sorted(PACKAGES.items(), key=lambda item: -len(item[0])):
        text = re.sub(r"\bexperimental([./])" + re.escape(old) + r"(?=[./\s'\"),:]|$)",
                      lambda m: "prototypes" + m[1] + new, text)
    text = re.sub(r"\bexperimental(?=[./])", "prototypes", text)
    text = re.sub(r"\b(from|import) experimental\b", r"\1 prototypes", text)
    text = re.sub(r"""(['"])experimental\1(?=\s*/)""",
                  lambda m: m[1] + "prototypes" + m[1], text)
    return text


def main():
    if not (ROOT / "experimental").is_dir() or (ROOT / "prototypes").exists():
        raise SystemExit("This migration is one-time; check the audit before proceeding.")
    records = [{"old": "experimental", "new": "prototypes", "kind": "prototype_root"}]
    records += [{"old": f"experimental/{old}", "new": f"prototypes/{new}",
                 "kind": "prototype_package"} for old, new in PACKAGES.items()]
    code_roots = ["experimental", "scripts", "tests", "src", "research_tools",
                  "anchor_retrieval", "combination_testing", "generic_composition",
                  "relational_gap", "relation_search"]
    changed = []
    # Save exact sources before changing imports or source-file manifest paths.
    for directory in code_roots:
        for path in sorted((ROOT / directory).rglob("*.py")):
            if path.is_symlink():
                continue
            before = path.read_text()
            after = rewrite_modules(before)
            if before == after:
                continue
            relative = path.relative_to(ROOT).as_posix()
            backup = AUDIT / "before_prototype_imports" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(path.read_bytes())
            changed.append({"path_before": relative, "sha256_before":
                            hashlib.sha256(path.read_bytes()).hexdigest(),
                            "sha256_after": hashlib.sha256(after.encode()).hexdigest()})
            path.write_text(after)
    for old, new in PACKAGES.items():
        (ROOT / "experimental" / old).rename(ROOT / "experimental" / new)
    (ROOT / "experimental").rename(ROOT / "prototypes")
    for row in changed:
        parts = Path(row["path_before"]).parts
        if parts[0] == "experimental":
            row["path_after"] = str(Path("prototypes", PACKAGES.get(parts[1], parts[1]), *parts[2:]))
        else:
            row["path_after"] = row["path_before"]
    path_map = ROOT / "results/path_map.json"
    mapping = json.loads(path_map.read_text())
    mapping["mappings"] += records
    mapping["mappings"].sort(key=lambda row: row["old"])
    path_map.write_text(dump(mapping))
    output = io.StringIO()
    writer = csv.DictWriter(output, ["old", "new", "kind"], delimiter="\t",
                            lineterminator="\n", extrasaction="ignore")
    writer.writeheader()
    writer.writerows(mapping["mappings"])
    (ROOT / "results/path_map.tsv").write_text(output.getvalue())
    layout_path = ROOT / "experiments/directory_layout.json"
    layout = json.loads(layout_path.read_text())
    layout["prototype_moves"] = records
    layout_path.write_text(dump(layout))
    (AUDIT / "prototype_migration.json").write_text(dump({
        "moves": records, "changed_sources": changed,
        "source_backups": str((AUDIT / "before_prototype_imports").relative_to(ROOT)),
        "scope": "Package names, import addresses and source-file path literals only.",
    }))
    print(dump({"renamed_directories": len(records), "updated_python_files": len(changed)}))


if __name__ == "__main__":
    main()
