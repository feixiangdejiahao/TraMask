"""Close explicitly relocated historical Go helpers from source declarations.

This is binding repair for both source controls and generated tests. It neither
invents helpers nor treats a recovered historical file as a passing execution.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from anchor_retrieval.syntax import Source, child, walk
from scripts.go_materialization import _binary


_UNIVERSE = set("""any comparable bool byte complex64 complex128 error float32 float64
int int8 int16 int32 int64 rune string uint uint8 uint16 uint32 uint64 uintptr
true false iota nil append cap clear close complex copy delete imag len make max
min new panic print println real recover""".split())
_DECLARATIONS = {"function_declaration", "method_declaration", "type_declaration",
                 "const_declaration", "var_declaration"}


def _analyze(files, repository):
    if not files:
        return {}
    result = subprocess.run(
        [str(_binary())], input=json.dumps({"files": [{"path": p, "code": c} for p, c in files.items()],
                                          "repository": str(repository), "analyze_only": True}),
        text=True, capture_output=True, timeout=60, check=True)
    return {row["path"]: row for row in json.loads(result.stdout)}


def _step(metadata):
    value = metadata.get("step_id")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _relocations(metadata):
    digest = metadata.get("sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        return {}
    return {name + "_rh_" + digest[:12]: name for name in metadata.get("relocated_globals", [])
            if isinstance(name, str) and name and name != "_"}


def _replace(code, edits):
    data = code.encode()
    for start, end, before, after in sorted(set(edits), reverse=True):
        if data[start:end].decode() != before:
            raise ValueError("historical helper source span mismatch")
        data = data[:start] + after.encode() + data[end:]
    return data.decode()


def _canonical(code, relocations):
    source = Source("canonical.go", code, "go")
    return _replace(code, [(n.start_byte, n.end_byte, source.text(n), relocations[source.text(n)])
                           for n in walk(source.root) if n.type in {"identifier", "type_identifier"}
                           and source.text(n) in relocations])


@dataclass
class _Declaration:
    key: str
    path: str
    start: int
    end: int
    code: str
    package: str
    metadata: dict
    names: tuple = ()
    unresolved: list = field(default_factory=list)
    imports: dict = field(default_factory=dict)
    receiver: str | None = None
    type_names: tuple = ()
    canonical: str = ""

    @property
    def group(self):
        return str(PurePosixPath(self.path).parent), self.package

    @property
    def support_path(self):
        digest = hashlib.sha256((self.path + ":" + str(self.start) + ":" + self.code).encode()).hexdigest()[:20]
        return str(PurePosixPath(self.path).parent / ("zz_rh_dependency_" + digest + "_test.go"))


class _Unresolved(Exception):
    def __init__(self, name, reason, candidates=()):
        self.name, self.reason, self.candidates = name, reason, list(candidates)


def recover_go_dependencies(files: dict[str, str], corpus: dict, selection: dict, repository: Path):
    """Return source-backed Go dependency edits and explicit unresolved records.

    Only historical donors with recorded relocation metadata are candidates.
    Each missing reference gets a transactional declaration closure. Package
    globals already present on disk or in ``files`` keep their binding. Ordering
    between historical versions is used only for one recorded original path and
    numeric source steps. Source parser/build compatibility remains a replay check.
    """
    output, records = dict(files), []
    metadata = selection.get("files", {})
    go_files = {p: c for p, c in files.items() if p.endswith(".go")}
    if not go_files:
        return output, records
    repository = Path(repository)
    source_codes = dict(go_files)
    donor_paths, donor_codes = set(), {}
    for path, row in corpus.get("sources", {}).items():
        meta = metadata.get(path, {})
        code = row.get("code") if isinstance(row, dict) else row
        if path.endswith(".go") and meta.get("kind") == "historical_validation" and isinstance(code, str):
            if _relocations(meta):
                donor_paths.add(path)
                donor_codes[path] = code
                source_codes.setdefault(path, code)
    # Read only sibling package sources; emitted snapshots override disk files.
    disk_paths = set()
    root = repository.resolve()
    for parent in sorted({str(PurePosixPath(p).parent) for p in go_files}):
        directory = (root / parent).resolve()
        if not directory.is_relative_to(root) or not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.go")):
            relative = path.relative_to(root).as_posix()
            if relative not in source_codes:
                source_codes[relative] = path.read_text()
                disk_paths.add(relative)
    valid = {}
    sources = {}
    for path, code in source_codes.items():
        source = Source(path, code, "go")
        if source.root.has_error:
            if path in go_files:
                records.append({"kind": "go_history_dependency", "path": path, "status": "unresolved",
                                "reason": "source_parse_error"})
            continue
        sources[path], valid[path] = source, code
    try:
        analyses = _analyze(valid, repository)
    except subprocess.CalledProcessError:
        analyses = {}
        for path, code in valid.items():
            try:
                analyses.update(_analyze({path: code}, repository))
            except subprocess.CalledProcessError:
                records.append({"kind": "go_history_dependency", "path": path, "status": "unresolved",
                                "reason": "go_parser_error"})

    existing = {}
    for path in go_files.keys() | disk_paths:
        if path in analyses:
            group = (str(PurePosixPath(path).parent), analyses[path]["package"])
            existing.setdefault(group, set()).update(analyses[path]["globals"])

    # Generated snapshots may share a path with a historical source. Analyze
    # recipients at their emitted offsets, but recover declarations exclusively
    # from the immutable corpus source, never from a generated test body.
    donor_analyses = {p: analyses[p] for p in donor_paths & analyses.keys()
                      if source_codes[p] == donor_codes[p]}
    donor_sources = {p: sources[p] for p in donor_analyses}
    changed_donors = {}
    for path in donor_paths - donor_analyses.keys():
        source = Source(path, donor_codes[path], "go")
        if not source.root.has_error:
            donor_sources[path] = source
            changed_donors[path] = donor_codes[path]
    if changed_donors:
        try:
            donor_analyses.update(_analyze(changed_donors, repository))
        except subprocess.CalledProcessError:
            for path, code in changed_donors.items():
                try:
                    donor_analyses.update(_analyze({path: code}, repository))
                except subprocess.CalledProcessError:
                    pass  # Invalid historical declarations cannot prove a binding.

    declarations, shells = {}, {}
    source_imports = {}
    for path in sorted(donor_analyses):
        source, analysis = donor_sources[path], donor_analyses[path]
        specs = [n for n in walk(source.root) if n.type == "import_spec"]
        source_imports[path] = {row["name"]: {**row, "source": source.text(node)}
                                for row, node in zip(analysis["imports"], specs)}
        for node in source.root.named_children:
            if node.type not in _DECLARATIONS:
                continue
            name = child(node, "name")
            if node.type == "function_declaration" and source.text(name) == "init":
                continue  # Initialization is not a named helper dependency.
            key = path + ":" + str(node.start_byte)
            receiver = None
            if node.type == "method_declaration":
                recv = child(node, "receiver")
                types = [source.text(n) for n in walk(recv) if n.type == "type_identifier"] if recv else []
                receiver = types[0] if len(types) == 1 else None
            type_names = tuple(source.text(child(n, "name")) for n in walk(node) if n.type in {"type_spec", "type_alias"}) if node.type == "type_declaration" else ()
            code = source.text(node)
            declaration = _Declaration(key, path, node.start_byte, node.end_byte, code,
                                       analysis["package"], metadata[path], receiver=receiver, type_names=type_names)
            # Keep a complete declaration group: iota and multi-name var specs
            # depend on their group and initializer evaluation order.
            prefix = "package " + analysis["package"] + "\n"
            declarations[key] = declaration
            shells[key] = prefix + code
    shell_analyses = _analyze(shells, repository)
    index, methods = {}, {}
    for key, declaration in declarations.items():
        row = shell_analyses[key]
        prefix_length = len(("package " + declaration.package + "\n").encode())
        declaration.names = tuple(row["globals"])
        source_analysis = donor_analyses[declaration.path]
        full_unresolved = {n["start_byte"] for n in source_analysis["unresolved"]}
        imports = source_imports[declaration.path]
        for reference in row["unresolved"]:
            offset = reference["start_byte"] - prefix_length
            name = reference["name"]
            if (declaration.start + offset not in full_unresolved and name not in source_analysis["globals"]
                    and name not in imports and name not in _UNIVERSE):
                continue  # A field key resolved by the complete source type.
            declaration.unresolved.append({**reference, "start_byte": offset,
                                           "end_byte": reference["end_byte"] - prefix_length})
            if name in imports:
                declaration.imports[name] = imports[name]
        canonical = _canonical(declaration.code, _relocations(declaration.metadata))
        declaration.canonical = canonical + "\n" + json.dumps(
            sorted((name, row["module"]) for name, row in declaration.imports.items()))
        if declaration.receiver:
            methods.setdefault((declaration.path, declaration.receiver), []).append(declaration)
        for name in declaration.names:
            if name == "_":
                continue
            index.setdefault((declaration.group, name), []).append(declaration)
            original = _relocations(declaration.metadata).get(name)
            if original and original != name:
                index.setdefault((declaration.group, original), []).append(declaration)

    def choose(name, group, context):
        candidates = index.get((group, name), [])
        if not candidates:
            raise _Unresolved(name, "no_source_definition")
        # Exact recorded relocated spellings establish source identity directly.
        exact = [d for d in candidates if name in d.names]
        if exact:
            candidates = exact
        if len(candidates) == 1:
            return candidates[0], "unique_source_definition"
        # Identical leaf declarations are one implementation. Non-leaf closure
        # may bind differently across versions and requires temporal evidence.
        leaf = all(all(r["name"] in _UNIVERSE or r["name"] in d.imports for r in d.unresolved)
                   and not d.type_names for d in candidates)
        if leaf and len({d.canonical for d in candidates}) == 1:
            return sorted(candidates, key=lambda d: d.key)[0], "identical_canonical_source_definitions"
        origins = {d.metadata.get("original_target_path") for d in candidates}
        step = _step(context)
        if len(origins) == 1 and None not in origins and step is not None and all(_step(d.metadata) is not None for d in candidates):
            prior = [d for d in candidates if _step(d.metadata) <= step]
            if prior:
                latest = max(_step(d.metadata) for d in prior)
                winners = [d for d in prior if _step(d.metadata) == latest]
                if len(winners) == 1:
                    return winners[0], "latest_prior_source_version"
        raise _Unresolved(name, "ambiguous_source_definitions", [d.key for d in candidates])

    committed = {}
    committed_names = {}
    for path in sorted(go_files):
        if path not in analyses:
            continue
        analysis = analyses[path]
        group = (str(PurePosixPath(path).parent), analysis["package"])
        imports = {row["name"] for row in analysis["imports"]}
        edits = []
        # An original bare name must not be interpreted as a historical suffix.
        # Every mapping below comes from selection.relocated_globals + sha256.
        for reference in analysis["unresolved"]:
            name = reference["name"]
            if name in imports or name in _UNIVERSE or name in existing.get(group, set()):
                continue
            planned, planning_names, evidence = {}, {}, []

            def recover(wanted, context):
                if wanted in existing.get(group, set()) or wanted in _UNIVERSE:
                    return wanted
                if wanted in committed_names.get(group, {}):
                    return wanted
                if wanted in planning_names:
                    return wanted
                declaration, reason = choose(wanted, group, context)
                aliases = _relocations(declaration.metadata)
                targets = [n for n in declaration.names if n == wanted or aliases.get(n) == wanted]
                if len(targets) != 1:
                    raise _Unresolved(wanted, "declaration_binding_not_unique", [declaration.key])
                actual = targets[0]
                if actual in existing.get(group, set()) or actual in committed_names.get(group, {}):
                    return actual
                add(declaration, reason)
                return actual

            def add(declaration, reason):
                if declaration.key in committed or declaration.key in planned:
                    return
                for defined in declaration.names:
                    if defined in existing.get(group, set()) or (defined in planning_names and planning_names[defined] != declaration.key):
                        raise _Unresolved(defined, "declaration_group_binding_conflict", [declaration.key])
                planned[declaration.key] = None
                planning_names.update({n: declaration.key for n in declaration.names})
                nested_edits = []
                for dependency in declaration.unresolved:
                    dependent = dependency["name"]
                    if dependent in declaration.imports or dependent in _UNIVERSE:
                        continue
                    if "." in source_imports[declaration.path]:
                        raise _Unresolved(dependent, "dot_import_binding_unknown", [declaration.key])
                    replacement = recover(dependent, declaration.metadata)
                    if replacement != dependent:
                        nested_edits.append((dependency["start_byte"], dependency["end_byte"], dependent, replacement))
                code = _replace(declaration.code, nested_edits)
                header = "package " + declaration.package + "\n"
                for imported in declaration.imports.values():
                    header += "import " + imported["source"] + "\n"
                planned[declaration.key] = header + "\n" + code + "\n"
                evidence.append({"source_path": declaration.path, "start_byte": declaration.start,
                                 "end_byte": declaration.end, "source_sha256": hashlib.sha256(declaration.code.encode()).hexdigest(),
                                 "names": list(declaration.names), "step_id": declaration.metadata.get("step_id"),
                                 "original_target_path": declaration.metadata.get("original_target_path"),
                                 "resolution": reason, "dependency_edits": [list(e) for e in nested_edits]})
                for typename in declaration.type_names:
                    for method in methods.get((declaration.path, typename), []):
                        add(method, "methods_of_recovered_source_type")

            try:
                replacement = recover(name, metadata.get(path, {}))
                for key, code in planned.items():
                    support = declarations[key].support_path
                    if support in output and output[support] != code:
                        raise _Unresolved(name, "support_path_collision", [key])
                for key, code in planned.items():
                    output[declarations[key].support_path] = code
                    committed[key] = code
                committed_names.setdefault(group, {}).update(planning_names)
                if replacement != name:
                    edits.append((reference["start_byte"], reference["end_byte"], name, replacement))
                records.append({"kind": "go_history_dependency", "path": path, "status": "recovered",
                                "name": name, "replacement": replacement,
                                "start_byte": reference["start_byte"], "end_byte": reference["end_byte"],
                                "declarations": evidence,
                                "support_paths": sorted(declarations[k].support_path for k in planned),
                                "execution_status": "source_control_replay_required"})
            except _Unresolved as error:
                records.append({"kind": "go_history_dependency", "path": path, "status": "unresolved",
                                "name": name, "dependency": error.name, "reason": error.reason,
                                "candidates": error.candidates,
                                "start_byte": reference["start_byte"], "end_byte": reference["end_byte"]})
        output[path] = _replace(go_files[path], edits)
    return output, records
