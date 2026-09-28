from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend
from relational_gap.source_dependencies import dependency_closure


def test_unchanged_wrapper_class_is_recovered_through_import_reexport_closure():
    files = {
        "sample.test.ts": '''import { Box } from "~/public.js";
test("wrapper", () => { const box = new Box(); expect(box.parse({mode: "write"})).toBe("write"); });''',
        "src/public.ts": 'export { Holder as Box } from "./wrapper.js";',
        "src/wrapper.ts": '''import { normalize } from "./normalize.js";
export class Holder { parse(options: Options) { return normalize(options); } }''',
        "src/normalize.ts": 'export function normalize({mode = "write"}: Options) { return mode; }',
        "src/unrelated.ts": "export const value = 10;",
    }
    selected = ["sample.test.ts", "src/normalize.ts"]
    aliases = {"~/*": ["src/*"]}
    recovered = dependency_closure(files, selected, "typescript", module_aliases=aliases)
    assert recovered["additional_paths"] == ["src/public.ts", "src/wrapper.ts"]
    assert "src/unrelated.ts" not in recovered["additional_paths"]
    assert any(edge["kind"] == "reexport" and edge["to"] == "src/wrapper.ts" for edge in recovered["edges"])
    data = extract_frontend([Source(path, files[path], "typescript") for path in selected + recovered["additional_paths"]],
                            module_aliases=aliases)
    call = next(c for c in data["calls"] if c["callee"] == "box.parse")
    assert call["targets"][0]["reason"] == "source_constructor_receiver"
    assert data["field_defaults"][0]["caller_bindings"][0]["call_id"] == call["id"]


def test_no_unconfigured_tilde_alias_is_guessed():
    files = {"test.ts": 'import { Box } from "~/box";', "src/box.ts": "export class Box {}"}
    result = dependency_closure(files, ["test.ts"], "typescript")
    assert not result["additional_paths"]
    assert result["unknowns"][0]["resolution"] == "external_or_unconfigured_module"


def test_tsconfig_base_url_paths_and_source_extensions_are_applied():
    files = {"test.ts": 'import { A } from "pkg/a.mjs";', "src/pkg/a.mts": 'export { A } from "./b.js";',
             "src/pkg/b.ts": "export class A {}"}
    result = dependency_closure(files, ["test.ts"], "typescript", module_base_url="src")
    assert result["additional_paths"] == ["src/pkg/a.mts", "src/pkg/b.ts"]


def test_python_src_initializer_reexport_and_relative_dependency_chain():
    files = {
        "tests/test_value.py": "from pkg import Container\n",
        "src/pkg/__init__.py": "from .wrapper import Container\n",
        "src/pkg/wrapper.py": "from .core import normalize\nclass Container:\n    pass\n",
        "src/pkg/core.py": "from . import constants\ndef normalize(value):\n    return value\n",
        "src/pkg/constants.py": "DEFAULT = 3\n",
        "src/unrelated.py": "VALUE = 1\n",
    }
    result = dependency_closure(files, ["tests/test_value.py"], "python")
    assert result["additional_paths"] == ["src/pkg/__init__.py", "src/pkg/wrapper.py", "src/pkg/core.py", "src/pkg/constants.py"]
    assert not result["counts"]["budget_exhausted"]


def test_python_from_import_submodule_without_initializer_and_parent_relative():
    files = {"tests/test_value.py": "from pkg import entry\n", "src/pkg/entry.py": "from .nested import impl\n",
             "src/pkg/nested/impl.py": "from .. import value\n", "src/pkg/value.py": "VALUE = 1\n"}
    result = dependency_closure(files, ["tests/test_value.py"], "python")
    assert result["additional_paths"] == ["src/pkg/entry.py", "src/pkg/nested/impl.py", "src/pkg/value.py"]


def test_go_package_members_and_explicit_local_module_imports():
    files = {"go.mod": "module example.test/project\n", "api/api_test.go": 'package api\nimport "example.test/project/internal/value"\n',
             "api/api.go": "package api\n", "api/helper.go": "package api\n",
             "internal/value/value.go": "package value\n", "internal/value/extra.go": "package value\n",
             "internal/value/other_test.go": "package value\n"}
    result = dependency_closure(files, ["api/api_test.go"], "go")
    assert result["additional_paths"] == ["api/api.go", "api/helper.go", "internal/value/extra.go", "internal/value/value.go"]
    assert "internal/value/other_test.go" not in result["additional_paths"]
    assert any(edge["resolution"] == "explicit_go_module_package" for edge in result["edges"])


def test_budgets_cycles_missing_sources_and_parse_errors_stay_explicit():
    files = {"a.ts": 'export * from "./b";', "b.ts": 'export * from "./a"; export * from "./c";', "c.ts": "export const x = 1;"}
    limited = dependency_closure(files, ["a.ts"], "typescript", max_additional=1)
    assert limited["additional_paths"] == ["b.ts"]
    assert limited["counts"]["budget_exhausted"]
    assert any(edge["to"] == "c.ts" and not edge["included"] for edge in limited["edges"])
    depth = dependency_closure(files, ["a.ts"], "typescript", max_depth=1)
    assert depth["additional_paths"] == ["b.ts"]
    assert depth["counts"]["depth_limit_reached"]
    missing = dependency_closure(files, ["missing.ts"], "typescript")
    assert missing["unknowns"][0]["reason"] == "selected_source_missing"
    malformed = dependency_closure({"bad.py": "def broken(:\n"}, ["bad.py"], "python")
    assert malformed["unknowns"][0]["reason"] == "source_parse_error"
