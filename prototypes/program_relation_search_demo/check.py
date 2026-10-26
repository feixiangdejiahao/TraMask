"""Mechanism checks, not pilot evaluation or evidence of semantic correctness."""
import ast
import hashlib
import json
from pathlib import Path
from kernel import run

ROOT = Path(__file__).parent
ARTIFACTS = ROOT / "artifacts"
ARTIFACTS.mkdir(exist_ok=True)
checks = []


def require(condition, label):
    assert condition, label
    checks.append(label)


def signature(report):
    return [(r["profile"], r["status"], r["new_profile"], len(r["new_target_lines"]))
            for r in report["results"]]


reports = {}
for path in sorted((ROOT / "fixtures").glob("*.py")):
    result = run(path.read_text(), str(path), budget=100)
    reports[path.stem] = result
    (ARTIFACTS / (path.stem + ".json")).write_text(json.dumps(result, indent=2) + "\n")

numeric = reports["equality"]
base = numeric["results"][0]
equality = [r for r in numeric["results"] if r["arguments"][0] == r["arguments"][1]
            and r["arguments"][0] > 0 and r["new_profile"]]
require(bool(equality), "numeric joint equality reached without manual terms")
require(any(r["target_lines"] == base["target_lines"] and not r["new_target_lines"] for r in equality),
        "new equality profile exists with identical target line coverage")
require(any(r["source_assertion_evaluated"] and r["status"] == "assertion_failure" for r in equality),
        "original assertion executed; failure recorded without calling it a defect")
records = reports["presence"]["results"]
partial = [r for r in records if any(0 < len(m) < 2 for m in r["arguments"])]
require(bool(partial) and all(r["source_assertion_evaluated"] for r in partial),
        "whole joint mapping mask reaches partial configurations and old assertions")
require(reports["presence"]["profiles"] == 16,
        "two mappings by two mechanically recovered keys yield all 16 joint masks")
require(bool(reports["non_equivalence"]["same_profile_different_actual"]),
        "negative control: same profile does not imply same actual output")

source = (ROOT / "fixtures/equality.py").read_text()
tree = ast.parse(source)
identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
identifiers |= {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
identifiers |= {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


class Rename(ast.NodeTransformer):
    def visit_Name(self, node):
        node.id += "_renamed" if node.id in identifiers else ""
        return node

    def visit_arg(self, node):
        node.arg += "_renamed"
        return node

    def visit_FunctionDef(self, node):
        node.name += "_renamed"
        return self.generic_visit(node)


class Translate(ast.NodeTransformer):
    def visit_Constant(self, node):
        if type(node.value) is int:
            node.value += 17
        return node


renamed = run(ast.unparse(Rename().visit(ast.parse(source))), "<renamed>", 100)
translated = run(ast.unparse(Translate().visit(ast.parse(source))), "<translated>", 100)
require(signature(renamed) == signature(numeric), "identifier renaming preserves profile search trace")
require(signature(translated) == signature(numeric), "numeric translation preserves profile search trace")
multi = source.split("def test_span")[0] + "def test_span():\n    assert span(2, 5) is False\n    assert span(7, 4) is False\n"
multiple = run(multi, "<multiple-calls>", budget=2)
require(multiple["results"][1]["profile"]["order"][0][-1] == 1,
        "trace attributes arguments to the selected call, not another call to the same API")
summary = dict(kind="synthetic mechanism fixtures only", checks=checks,
               files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT / "kernel.py", ROOT / "check.py"]},
               results={name: {k: r[k] for k in ["executed", "profiles", "seed_count"]} for name, r in reports.items()},
               limitations=["line coverage only, not branch coverage", "no semantic equivalence or bug verdict", "no aliases/phase/producer propagation", "bounded literal-argument heuristic"])
(ARTIFACTS / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
