"""Recover absent validation files from literal recorded writes, without execution.

The result is an explicit evaluation harness added AFTER terminal P validation.
It is never part of the claim that a replay checkpoint matches submission state.
Only quoted shell heredocs and a narrow literal Python replacement grammar are
supported. Unknown transformations require further evidence, not guessed bytes.
"""
from __future__ import annotations
import ast
import hashlib
import posixpath
import re

from tramask_pilot.corpus import calls


def _resolve(name, cwd):
    value = posixpath.normpath(name if name.startswith("/") else cwd + "/" + name)
    if not value.startswith(("/app/", "/tmp/")) or "/.git/" in value:
        raise ValueError("capsule_path_outside_subject")
    return value


def _cwd(prefix):
    cwd = "/app"
    for match in re.finditer(r"(?:^|&&|;|\n)\s*cd\s+([^\s;&|]+)", prefix):
        path = match.group(1).strip("\"'")
        cwd = posixpath.normpath(path if path.startswith("/") else cwd + "/" + path)
    return cwd


def _digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _python_literal_edits(code, cwd, contents, allowlist):
    tree = ast.parse(code)
    variables, changes = {}, []

    def value(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, int)):
            return node.value
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return value(node.left) + value(node.right)
        raise ValueError("nonliteral_capsule_expression")

    active_path = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, expression = node.targets[0].id, node.value
            try:
                variables[name] = value(expression)
                continue
            except (ValueError, TypeError):
                pass
            if isinstance(expression, ast.Call) and isinstance(expression.func, ast.Attribute):
                receiver = expression.func.value
                if expression.func.attr == "read" and isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "open":
                    try:
                        path = _resolve(value(receiver.args[0]), cwd)
                    except (ValueError, IndexError):
                        continue
                    active_path = path
                    if path in allowlist:
                        if path not in contents:
                            raise ValueError("literal_replacement_without_prior_file: " + path)
                        variables[name] = contents[path]
                elif expression.func.attr == "replace" and active_path in allowlist:
                    original = value(receiver)
                    args = [value(arg) for arg in expression.args]
                    if len(args) not in (2, 3) or not all(isinstance(v, str) for v in args[:2]):
                        raise ValueError("unsupported_literal_replace")
                    if not args[0] or args[0] not in original:
                        raise ValueError("literal_replacement_anchor_absent")
                    variables[name] = original.replace(*args)
                elif active_path in allowlist:
                    raise ValueError("unsupported_capsule_transformation")
        elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if not (isinstance(call.func, ast.Attribute) and call.func.attr == "write"):
                continue
            receiver = call.func.value
            if not (isinstance(receiver, ast.Call) and isinstance(receiver.func, ast.Name) and receiver.func.id == "open"):
                continue
            path = _resolve(value(receiver.args[0]), cwd)
            if path in allowlist:
                before = contents.get(path)
                after = value(call.args[0])
                if not isinstance(after, str):
                    raise ValueError("capsule_requires_text_write")
                contents[path] = after
                changes.append({"path": path, "kind": "literal_python_write", "before_sha256": _digest(before) if before is not None else None, "after_sha256": _digest(after)})
    return changes


def recover_literal_capsule(trajectory, selected_call_id, selected_command, paths):
    """Interpret literal writes only up to the selected test's invocation boundary."""
    allowlist = {_resolve(path, "/app") for path in paths}
    contents, evidence = {}, []
    found = False
    for action in calls(trajectory):
        command = action["command"]
        if action["id"] == selected_call_id:
            if not command.strip().endswith(selected_command.strip()):
                raise ValueError("selected_test_not_exact_suffix")
            command = command.strip()[:-len(selected_command.strip())]
            found = True
        # Quoted delimiters disable shell expansion, preserving literal bytes.
        pattern = re.compile(r"(?P<header>(?:cat\s*(?P<op>>>|>)\s*(?P<path>[^\s<]+)|python(?:3)?\s+-)\s*<<\s*['\"](?P<tag>[A-Za-z0-9_]+)['\"][^\n]*\n)(?P<body>.*?)(?m:^(?P=tag)\s*$)", re.S)
        stripped_prefix = ""
        previous_end = 0
        for match in pattern.finditer(command):
            stripped_prefix += command[previous_end:match.start()]
            cwd = _cwd(stripped_prefix)
            body = match.group("body")
            if match.group("path"):
                path = _resolve(match.group("path").strip("\"'"), cwd)
                if path in allowlist:
                    before = contents.get(path)
                    if match.group("op") == ">>" and before is None:
                        raise ValueError("literal_append_without_prior_file")
                    after = (before + body) if match.group("op") == ">>" else body
                    contents[path] = after
                    evidence.append({"action_id": action["id"], "path": path, "kind": "quoted_heredoc_append" if match.group("op") == ">>" else "quoted_heredoc",
                                     "command_sha256": _digest(action["command"]),
                                     "before_sha256": _digest(before) if before is not None else None,
                                     "after_sha256": _digest(after), "body_start_char": match.start("body"), "body_end_char": match.end("body")})
            else:
                try:
                    changes = _python_literal_edits(body, cwd, contents, allowlist)
                except ValueError as error:
                    raise ValueError(action["id"] + ": " + str(error)) from error
                evidence.extend({**change, "action_id": action["id"], "command_sha256": _digest(action["command"])} for change in changes)
            previous_end = match.end()
        if found:
            break
    if not found:
        raise ValueError("selected_call_not_found")
    missing = sorted(allowlist - contents.keys())
    return {"status": "reconstructed_pending_independent_authority_check" if not missing else "incomplete",
            "files": {p: {"content": contents[p], "sha256": _digest(contents[p])} for p in sorted(contents)},
            "missing": missing, "literal_write_evidence": evidence,
            "selected_call_id": selected_call_id, "selected_command_sha256": _digest(selected_command),
            "limits": "Supports literal writes only. Caller must rule out unsupported writes/copies/formatting and independently check recovered bytes. This is not a terminal filesystem restoration."}
