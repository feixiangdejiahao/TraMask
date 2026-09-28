"""Bounded source dependency recovery before construction of the program index.

Inputs are already-owned source texts, never case metadata or filesystem paths
to execute. Import and package edges select context; they do not prove runtime
loading, dynamic dispatch, build tags, or test execution.
"""
from __future__ import annotations

import ast
import collections
import posixpath
import re

from anchor_retrieval.syntax import Source, child, literal, walk


def _ordered(items):
    return list(dict.fromkeys(items))


def _ts_paths(files, source_path, module, aliases, base_url):
    def candidates(base):
        base = posixpath.normpath(base)
        options = [base]
        stem, extension = posixpath.splitext(base)
        replacements = {".js": [".ts", ".tsx"], ".jsx": [".tsx", ".ts"],
                        ".mjs": [".mts", ".ts"], ".cjs": [".cts", ".ts"]}
        if extension in replacements:
            options.extend(stem + suffix for suffix in replacements[extension])
        if not extension:
            options.extend(base + suffix for suffix in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx"))
            options.extend(base + "/index" + suffix for suffix in (".ts", ".tsx", ".mts", ".cts", ".js"))
        return [path for path in _ordered(options) if path in files]
    if module.startswith("."):
        return candidates(posixpath.join(posixpath.dirname(source_path), module)), "relative_module"
    matches = []
    for pattern, targets in aliases.items():
        if "*" in pattern:
            prefix, suffix = pattern.split("*")
            if not module.startswith(prefix) or not module.endswith(suffix) or len(module) < len(prefix) + len(suffix):
                continue
            capture = module[len(prefix):len(module) - len(suffix) if suffix else None]
        elif module == pattern:
            capture = ""
        else:
            continue
        matches.append((("*" not in pattern, len(pattern.split("*", 1)[0])), pattern, targets, capture))
    if matches:
        _, _, targets, capture = max(matches, key=lambda item: (item[0], item[1]))
        for target in targets:
            paths = candidates(posixpath.join(base_url or "", target.replace("*", capture)))
            if paths:
                return paths, "configured_paths_alias"
    if base_url is not None:
        return candidates(posixpath.join(base_url, module)), "configured_base_url"
    return [], "external_or_unconfigured_module"


def _python_paths(files, source_path, module, level, members):
    def exact(base):
        base = posixpath.normpath(base)
        return [path for path in (base + ".py", base + "/__init__.py") if path in files]
    path = module.replace(".", "/")
    if level:
        base = posixpath.dirname(source_path)
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        path = posixpath.normpath(posixpath.join(base, path))
        roots = [path]
        found = exact(path)
        if not module and path + "/__init__.py" in files:
            found.append(path + "/__init__.py")
        reason = "relative_python_import"
    else:
        roots = [path, "src/" + path]
        found = [p for root in roots for p in exact(root)]
        suffixes = ("/" + path + ".py", "/" + path + "/__init__.py")
        additional = [p for p in sorted(files) if p.endswith(suffixes)]
        found.extend(additional)
        roots.extend(p[:-3] if p.endswith(".py") and not p.endswith("/__init__.py") else p[:-12] for p in additional)
        reason = "absolute_python_source_lookup"
    # A from-import can name a submodule or an exported class/function. Include
    # existing submodule files and the package initializer, leaving symbol
    # disambiguation to the subsequent source index.
    for member in members:
        if member != "*":
            found.extend(p for root in _ordered(roots) for p in exact(root + "/" + member.replace(".", "/")))
    for target in list(found):
        directory = posixpath.dirname(target)
        while directory:
            initializer = directory + "/__init__.py"
            if initializer in files:
                found.append(initializer)
            directory = posixpath.dirname(directory)
    return sorted(set(found)), reason


def _imports(path, code, language):
    if language == "python":
        try:
            root = ast.parse(code)
        except (SyntaxError, ValueError, RecursionError):
            return [], "source_parse_error"
        found = []
        for node in ast.walk(root):
            if isinstance(node, ast.Import):
                found.extend({"module": alias.name, "members": [], "level": 0, "kind": "import", "line": node.lineno}
                             for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                found.append({"module": node.module or "", "members": [alias.name for alias in node.names],
                              "level": node.level, "kind": "from_import", "line": node.lineno})
        return sorted(found, key=lambda item: (item["line"], item["module"])), None
    source = Source(path, code, language)
    found = []
    for node in walk(source.root):
        if language == "typescript" and node.type in {"import_statement", "export_statement"}:
            module_node = child(node, "source")
            kind = "reexport" if node.type == "export_statement" else "import"
        elif language == "go" and node.type == "import_spec":
            module_node = child(node, "path")
            kind = "import"
        else:
            continue
        if module_node is None:
            continue
        try:
            module = literal(source.text(module_node))
        except ValueError:
            continue
        if isinstance(module, str):
            found.append({"module": module, "members": [], "level": 0, "kind": kind,
                          "line": node.start_point.row + 1})
    return found, "source_parse_error" if source.root.has_error else None


def dependency_closure(files: dict[str, str], selected: list[str], language: str, *,
                       module_aliases: dict | None = None, module_base_url: str | None = None,
                       max_additional: int = 256, max_depth: int = 4) -> dict:
    """Return deterministic additional source paths, edges, and unknowns.

    ``module_aliases`` and ``module_base_url`` must come from explicit project
    configuration. No '~/' convention is guessed. Go local import resolution
    requires the applicable ``go.mod`` text in ``files``; same-package source
    files can still be recovered without it. Python lookup includes repository
    and src layouts, retaining ambiguous suffix matches as source candidates.
    """
    if language not in {"python", "typescript", "go"}:
        raise ValueError("unsupported dependency language")
    if type(max_additional) is not int or type(max_depth) is not int or max_additional < 0 or max_depth < 0:
        raise ValueError("dependency bounds must be nonnegative integers")
    aliases = {}
    for pattern, targets in (module_aliases or {}).items():
        targets = [targets] if isinstance(targets, str) else targets
        if (not isinstance(pattern, str) or pattern.count("*") > 1 or not isinstance(targets, (list, tuple))
                or any(not isinstance(t, str) or t.count("*") > 1 for t in targets)):
            raise ValueError("invalid explicit module alias mapping")
        aliases[pattern] = list(targets)
    if module_base_url is not None and not isinstance(module_base_url, str):
        raise ValueError("module_base_url must be a string or None")
    initial = sorted(set(selected))
    included = set(initial)
    queue = collections.deque((path, 0) for path in initial)
    additional, edges, unknowns, visited, go_packages = [], [], [], set(), set()
    modules = []
    if language == "go":
        for path, code in sorted(files.items()):
            if posixpath.basename(path) == "go.mod":
                match = re.search(r"(?m)^\s*module\s+(?:\"([^\"]+)\"|([^\s]+))", code)
                if match:
                    modules.append((posixpath.dirname(path), match.group(1) or match.group(2)))
    budget_exhausted = False
    depth_exhausted = False
    def include(origin, target, depth, dependency, resolution):
        nonlocal budget_exhausted
        allowed = target in included or len(additional) < max_additional
        edges.append({"from": origin, "to": target, "kind": dependency["kind"], "module": dependency["module"],
                      "line": dependency.get("line"), "depth": depth + 1, "resolution": resolution, "included": allowed})
        if target in included:
            return
        if not allowed:
            budget_exhausted = True
            return
        included.add(target)
        additional.append(target)
        queue.append((target, depth + 1))
    while queue:
        path, depth = queue.popleft()
        if path in visited:
            continue
        visited.add(path)
        if path not in files:
            unknowns.append({"path": path, "reason": "selected_source_missing"})
            continue
        if depth >= max_depth:
            depth_exhausted = True
            continue
        imports, error = _imports(path, files[path], language)
        if error:
            unknowns.append({"path": path, "reason": error})
        if language == "go":
            directory = posixpath.dirname(path)
            if directory not in go_packages:
                go_packages.add(directory)
                for sibling in sorted(files):
                    if (sibling != path and posixpath.dirname(sibling) == directory
                            and sibling.endswith(".go") and not sibling.endswith("_test.go")):
                        include(path, sibling, depth, {"kind": "package_scope", "module": directory}, "same_go_package_directory")
        for dependency in imports:
            module = dependency["module"]
            if language == "typescript":
                targets, resolution = _ts_paths(files, path, module, aliases, module_base_url)
            elif language == "python":
                targets, resolution = _python_paths(files, path, module, dependency["level"], dependency["members"])
            else:
                matches = [(directory, prefix) for directory, prefix in modules
                           if module == prefix or module.startswith(prefix + "/")]
                targets = []
                for directory, prefix in sorted(matches, key=lambda item: (-len(item[1]), item[0])):
                    package_dir = posixpath.normpath(posixpath.join(directory, module[len(prefix):].lstrip("/")))
                    if package_dir == ".":
                        package_dir = ""
                    targets.extend(p for p in sorted(files) if posixpath.dirname(p) == package_dir
                                   and p.endswith(".go") and not p.endswith("_test.go"))
                resolution = "explicit_go_module_package" if matches else "external_or_missing_go_module_metadata"
            if not targets:
                unknowns.append({"path": path, "line": dependency.get("line"), "module": module,
                                 "kind": dependency["kind"], "reason": "external_or_missing_source", "resolution": resolution})
            for target in targets:
                include(path, target, depth, dependency, resolution)
    return {"additional_paths": additional, "edges": edges, "unknowns": unknowns,
            "counts": {"selected": len(initial), "additional": len(additional), "parsed_or_visited": len(visited),
                       "edges": len(edges), "unknowns": len(unknowns), "budget_exhausted": budget_exhausted,
                       "depth_limit_reached": depth_exhausted},
            "budget": {"max_additional": max_additional, "max_depth": max_depth},
            "precision": "syntactic_import_and_package_closure_runtime_loading_unknown"}
