"""Reject only source-proven Go call arity violations introduced by input edits.

This is a pre-compilation filter, not a type checker. Unknown package bindings,
receivers, tuple-valued arguments and incomplete source remain explicit unknowns.
The public ``filter_candidates`` preserves ordering and never mutates its inputs.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import posixpath

from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, walk


VERSION = "go-source-arity-v1"


@dataclass(frozen=True)
class Signature:
    path: str
    name: str
    start: int
    required: int
    variadic: bool
    owner: str = ""

    def evidence(self):
        return {"path": self.path, "name": self.name, "start_byte": self.start,
                "required": self.required, "variadic": self.variadic,
                "receiver_type": self.owner}


def _names(node):
    return [n for i, n in enumerate(node.children) if node.field_name_for_child(i) == "name"]


def _parameters(node):
    parameters = child(node, "parameters")
    if parameters is None:
        return None
    count, variadic = 0, False
    for parameter in parameters.named_children:
        if parameter.type == "comment":
            continue
        if parameter.type not in {"parameter_declaration", "variadic_parameter_declaration"}:
            return None
        if parameter.type == "variadic_parameter_declaration":
            variadic = True
        else:
            count += max(1, len(_names(parameter)))
    return count, variadic


def _base_type(source, node):
    if node is None:
        return None
    if node.type in {"pointer_type", "parenthesized_type"}:
        return _base_type(source, node.named_children[0]) if node.named_children else None
    if node.type in {"type_identifier", "qualified_type"}:
        return source.text(node)
    return None


def _within(outer, inner):
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


class ArityIndex:
    def __init__(self, corpus, frontend=None):
        self.corpus, self.frontend = corpus, frontend or {}
        self.sources, self.packages, self.declarations = {}, {}, defaultdict(list)
        self.by_span, self.calls = {}, {}
        self.resolved = {}
        self.modules = self.frontend.get("module_resolution", {}).get("go_modules", {})
        for path, metadata in corpus.get("sources", {}).items():
            if (metadata.get("language", corpus.get("language")) != "go" or metadata.get("parse_error")
                    or not metadata.get("complete_file", True)):
                continue
            source = Source(path, metadata["code"], "go", metadata.get("origin", "repository"),
                            written_path=metadata.get("written_path"))
            if source.root.has_error:
                continue
            package = next((n for n in source.root.named_children if n.type == "package_clause"), None)
            if package is None:
                continue
            package_name = source.text(package.named_children[-1])
            self.sources[path] = source
            self.packages[path] = (posixpath.dirname(source.lookup_path), package_name)
            for declaration in source.root.named_children:
                if declaration.type not in {"function_declaration", "method_declaration"}:
                    continue
                shape = _parameters(declaration)
                if shape is None:
                    continue
                receiver = child(declaration, "receiver")
                owner = ""
                if receiver is not None:
                    parameter = next(iter(receiver.named_children), None)
                    owner = _base_type(source, child(parameter, "type")) if parameter else None
                    if owner is None:
                        continue
                signature = Signature(path, source.text(child(declaration, "name")),
                                      declaration.start_byte, *shape, owner)
                self.declarations[(self.packages[path], owner, signature.name)].append(signature)
                self.by_span[(path, declaration.start_byte)] = signature
        for call in self.frontend.get("calls", []):
            span = call.get("span", {})
            self.calls[(span.get("path"), span.get("start_byte"), span.get("end_byte"))] = call
        self.functions = {f["id"]: f for f in self.frontend.get("functions", [])}

    def _local_binding(self, source, name, at):
        """Find lexical declarations that can shadow an import/package function."""
        scopes, node = [], at.parent
        while node is not None:
            scopes.append(node)
            node = node.parent
        matches = []
        for node in walk(source.root):
            if node.type in {"parameter_declaration", "variadic_parameter_declaration"}:
                if name not in {source.text(n) for n in _names(node)}:
                    continue
                owner = node.parent
                while owner is not None and owner.type not in {"function_declaration", "method_declaration", "func_literal"}:
                    owner = owner.parent
                if owner is not None and _within(owner, at):
                    matches.append((owner.end_byte-owner.start_byte, node.start_byte, child(node, "type"), None))
            elif node.type in {"short_var_declaration", "var_spec", "range_clause"} and node.start_byte < at.start_byte:
                names = child(node, "left")
                names = list(names.named_children) if names is not None else _names(node)
                if name not in {source.text(n) for n in names}:
                    continue
                scope = node.parent
                while scope is not None and scope.type not in {"block", "source_file", "for_statement", "if_statement"}:
                    scope = scope.parent
                if scope is None or not _within(scope, at):
                    continue
                values = child(node, "right", "value")
                values = list(values.named_children) if values is not None and values.type == "expression_list" else [values]
                value = values[names.index(next(n for n in names if source.text(n) == name))] if len(names) == len(values) else None
                matches.append((scope.end_byte-scope.start_byte, node.start_byte, child(node, "type"), value))
        return min(matches, key=lambda item: (item[0], -item[1])) if matches else None

    def _import_package(self, source, alias):
        imported = source.imports.get(alias)
        if not imported or alias in {".", "_"}:
            return None
        module = imported[0]
        paths = []
        for root, prefix in self.modules.items():
            if module == prefix or module.startswith(prefix + "/"):
                paths.append(posixpath.normpath(posixpath.join(root, module[len(prefix):].lstrip("/"))))
        if len(set(paths)) != 1:
            return None
        directory = paths[0]
        directory = "" if directory == "." else directory
        packages = {pkg for pkg in self.packages.values() if pkg[0] == directory and not pkg[1].endswith("_test")}
        return next(iter(packages)) if len(packages) == 1 else None

    def _type_package(self, source, spelling):
        if not spelling:
            return None
        if "." in spelling:
            alias, name = spelling.split(".", 1)
            package = self._import_package(source, alias)
        else:
            package, name = self.packages[source.path], spelling
        return (package, name) if package is not None else None

    def resolve(self, source, call):
        key = (source.path, call.start_byte, call.end_byte)
        if key not in self.resolved:
            self.resolved[key] = self._resolve(source, call)
        return self.resolved[key]

    def _resolve(self, source, call):
        function, _ = call_parts(call)
        if function is None:
            return None, "missing_callee"
        method_expression = False
        if function.type == "identifier":
            name = source.text(function)
            binding = self._local_binding(source, name, call)
            if binding is not None:
                value = binding[3]
                shape = _parameters(value) if value is not None and value.type == "func_literal" else None
                if shape is None:
                    return None, "unresolved_local_function_binding"
                return Signature(source.path, name, value.start_byte, *shape), "local_function_literal"
            key = (self.packages[source.path], "", name)
        elif function.type == "selector_expression":
            receiver, member = attr_parts(function)
            name = source.text(member)
            if receiver is None or receiver.type != "identifier":
                return None, "unsupported_receiver_expression"
            label = source.text(receiver)
            binding = self._local_binding(source, label, call)
            if binding is None and label in source.imports:
                package = self._import_package(source, label)
                if package is None:
                    return None, "unresolved_import_package"
                key = (package, "", name)
            elif binding is not None:
                spelling = _base_type(source, binding[2])
                value = binding[3]
                if spelling is None and value is not None:
                    if value.type == "unary_expression" and source.text(value).lstrip().startswith("&"):
                        value = next(iter(value.named_children), None)
                    if value is not None and value.type == "composite_literal":
                        spelling = _base_type(source, child(value, "type"))
                typed = self._type_package(source, spelling)
                if typed is None:
                    return None, "unresolved_receiver_type"
                key = (typed[0], typed[1], name)
            else:
                key = (self.packages[source.path], label, name)
                method_expression = True
        else:
            return None, "unsupported_callee_expression"
        matches = self.declarations.get(key, [])
        if len(matches) != 1:
            return None, "ambiguous_declaration" if matches else "unresolved_declaration"
        signature = matches[0]
        # Resolved frontend evidence can identify an exact declaration, but it
        # never overrides source-derived package/receiver identity above.
        call_fact = self.calls.get((source.path, call.start_byte, call.end_byte), {})
        targets = [t for t in call_fact.get("targets", []) if t.get("resolved")]
        method = "source_declaration"
        if len(targets) == 1:
            target = self.functions.get(targets[0].get("function_id"), {}).get("span", {})
            known = self.by_span.get((target.get("path"), target.get("start_byte")))
            if known == signature:
                method = "frontend_and_source_declaration"
        if method_expression:
            signature = Signature(signature.path, signature.name, signature.start,
                                  signature.required+1, signature.variadic, signature.owner)
            method += "_method_expression"
        return signature, method


def _call_changes(source, edits):
    """Yield changed argument lists whose original callee remains identical."""
    if not hasattr(source, "_arity_calls"):
        source._arity_calls = [node for node in walk(source.root) if node.type == "call_expression"]
    calls = source._arity_calls
    selected = {}
    for edit in edits:
        span = edit.get("span", {})
        if span.get("path") != source.path or edit.get("role") == "semantic_expected":
            continue
        containing = [node for node in calls if node.start_byte <= span.get("start_byte", -1)
                      and span.get("end_byte", -1) <= node.end_byte]
        if containing:
            node = min(containing, key=lambda n: n.end_byte-n.start_byte)
            selected[(node.start_byte, node.end_byte)] = node
    for node in selected.values():
        relevant = [edit for edit in edits if edit.get("span", {}).get("path") == source.path
                    and node.start_byte <= edit["span"]["start_byte"]
                    and edit["span"]["end_byte"] <= node.end_byte]
        data = source.data[node.start_byte:node.end_byte]
        valid, previous = True, node.end_byte+1
        for edit in sorted(relevant, key=lambda e: e["span"]["start_byte"], reverse=True):
            start, end = edit["span"]["start_byte"], edit["span"]["end_byte"]
            if end > previous or source.data[start:end].decode() != edit.get("before"):
                valid = False
                break
            data = data[:start-node.start_byte] + edit["after"].encode() + data[end-node.start_byte:]
            previous = start
        if not valid:
            yield node, None, "source_edit_mismatch"
            continue
        prefix = "package check\nfunc test(){\n"
        changed = Source("arity_fragment.go", prefix+data.decode()+"\n}", "go")
        after = next((n for n in walk(changed.root) if n.type == "call_expression"
                      and n.start_byte == len(prefix.encode()) and n.end_byte == len(prefix.encode())+len(data)), None)
        if changed.root.has_error or after is None:
            yield node, None, "unsupported_changed_call_shape"
            continue
        fn, before_args = call_parts(node)
        new_fn, after_args = call_parts(after)
        if source.text(fn) != changed.text(new_fn):
            continue
        if len(before_args) != len(after_args) or any(a.type == "variadic_argument" for a in before_args) != any(a.type == "variadic_argument" for a in after_args):
            yield node, after_args, None


def filter_candidates(corpus, candidates, frontend=None):
    """Return ``candidates``, rejected rows and a complete decision ledger.

    ``accepted`` proves argument count only. It says nothing about argument
    types or assertion correctness. Unsupported calls remain in the output.
    """
    if corpus.get("language") != "go":
        return {"version": VERSION, "candidates": list(candidates), "rejected": [],
                "records": [], "counts": {"input": len(candidates), "kept": len(candidates), "rejected": 0}}
    index = ArityIndex(corpus, frontend)
    kept, rejected, records = [], [], []
    for candidate in candidates:
        decisions = []
        paths = {edit.get("span", {}).get("path") for edit in candidate.get("edits", [])}
        for path in sorted(paths, key=str):
            source = index.sources.get(path)
            if source is None:
                decisions.append({"status": "unsupported", "reason": "source_unavailable", "path": path})
                continue
            for original, args, error in _call_changes(source, candidate.get("edits", [])):
                decision = {"path": path, "start_byte": original.start_byte,
                            "call": source.text(call_parts(original)[0])}
                signature, resolution = index.resolve(source, original) if error is None else (None, error)
                if signature is None:
                    decision.update(status="unsupported", reason=resolution)
                else:
                    spread = [i for i, arg in enumerate(args) if arg.type == "variadic_argument"]
                    decision.update(signature=signature.evidence(), resolution=resolution, actual_count=len(args))
                    if len(args) == 1 and args[0].type == "call_expression":
                        decision.update(status="unsupported", reason="possible_multi_result_argument")
                    elif spread:
                        legal = signature.variadic and spread == [len(args)-1] and len(args) == signature.required+1
                        decision.update(status="accepted" if legal else "rejected", reason="variadic_expansion_arity")
                    else:
                        legal = len(args) >= signature.required if signature.variadic else len(args) == signature.required
                        decision.update(status="accepted" if legal else "rejected", reason="declared_parameter_arity")
                decisions.append(decision)
        blocked = any(d["status"] == "rejected" for d in decisions)
        (rejected if blocked else kept).append(candidate)
        records.append({"candidate_id": candidate.get("id"), "status": "rejected" if blocked else
                        "unsupported" if any(d["status"] == "unsupported" for d in decisions) else
                        "accepted" if decisions else "unchanged_arity", "calls": decisions})
    counts = Counter(record["status"] for record in records)
    return {"version": VERSION, "candidates": kept, "rejected": rejected, "records": records,
            "counts": {"input": len(candidates), "kept": len(kept), "rejected": len(rejected),
                       "decisions": dict(counts)}}
