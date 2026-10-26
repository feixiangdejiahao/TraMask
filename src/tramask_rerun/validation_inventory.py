"""Pure, outcome-blind inventory of authored validation material and invocations.

Shell parsing here is deliberately conservative. An invocation appearing in an
executed shell action is not proof that a conditional branch ran or a suite
collected a particular test. Every extracted command requires review; this
module never executes commands, reads files, or uses a Pilot 1 target selection.
"""
from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import posixpath
import re
import shlex


_SCRIPT_EXTENSIONS = (".py", ".js", ".cjs", ".mjs", ".ts", ".tsx", ".go", ".sh")
_VALIDATION = re.compile(r"\b(?:assert|assertEqual|assertEquals|assert_that|expect|pytest|unittest|testing\.T)\b|console\.assert|\b(?:describe|it|test)\s*\(")


def _sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _path(value, cwd="/app"):
    if not isinstance(value, str) or not value or any(c in value for c in ("\0", "$", "`")):
        return None
    value = value.split("::", 1)[0]
    path = posixpath.normpath(value if value.startswith("/") else posixpath.join(cwd, value))
    return path if path in {"/app", "/tmp"} or path.startswith(("/app/", "/tmp/")) else None


def _test_path(path):
    name = posixpath.basename(path).lower()
    parts = set(path.lower().split("/"))
    return bool(parts & {"test", "tests", "spec", "specs", "__tests__"}
                or name.startswith("test_") or name.endswith(("_test.py", "_test.go"))
                or re.search(r"\.(?:test|spec)\.[cm]?[jt]sx?$", name))


def _calls(trajectory):
    if isinstance(trajectory, list):
        rows = []
        for index, row in enumerate(trajectory):
            if not isinstance(row, dict) or not isinstance(row.get("command"), str):
                raise ValueError("raw_calls_require_command_strings")
            rows.append({"id": row.get("id", f"call_{index}"), "command": row["command"],
                         "expected": row.get("expected"), "function": row.get("function", "bash")})
        return rows
    if not isinstance(trajectory, dict) or not isinstance(trajectory.get("steps", []), list):
        raise ValueError("trajectory_requires_steps_or_raw_call_list")
    rows = []
    for ordinal, step in enumerate(trajectory.get("steps", [])):
        calls = step.get("tool_calls") or []
        observations = (step.get("observation") or {}).get("results") or []
        for index, call in enumerate(calls):
            arguments = call.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            command = arguments.get("command") if isinstance(arguments, dict) else None
            if not isinstance(command, str):
                # Preserve unsupported raw tools as review items without
                # inventing executable shell text from their other arguments.
                rows.append({"id": f"s{step.get('step_id', ordinal)}_c{index}", "command": None,
                             "function": call.get("function_name"), "expected": None})
                continue
            expected = None
            if len(observations) == len(calls):
                content = observations[index].get("content")
                try:
                    expected = json.loads(content) if isinstance(content, str) else content
                except ValueError:
                    expected = {"output": content}
            rows.append({"id": f"s{step.get('step_id', ordinal)}_c{index}", "command": command,
                         "function": call.get("function_name"), "expected": expected})
    return rows


def _heredocs(command):
    rows, position = [], 0
    while position < len(command):
        newline = command.find("\n", position)
        if newline < 0:
            break
        header = command[position:newline]
        quote, escaped, offset = None, False, 0
        found = None
        while offset < len(header):
            char = header[offset]
            if escaped:
                escaped = False
            elif char == "\\" and quote != "'":
                escaped = True
            elif quote:
                if char == quote:
                    quote = None
            elif char in "'\"":
                quote = char
            elif header.startswith("<<", offset) and not header.startswith("<<<", offset):
                found = re.match(r"<<(?P<tabs>-?)\s*(?P<quote>['\"]?)(?P<delimiter>[A-Za-z_][A-Za-z_0-9]*)(?P=quote)", header[offset:])
                if found:
                    break
            offset += 1
        if not found:
            position = newline + 1
            continue
        cursor, closing = newline + 1, None
        while cursor < len(command):
            end = command.find("\n", cursor)
            end = len(command) if end < 0 else end
            line = command[cursor:end]
            if (line.lstrip("\t") if found["tabs"] else line) == found["delimiter"]:
                closing = (cursor, end + (end < len(command)))
                break
            cursor = end + 1
        body_end, end = closing if closing else (len(command), len(command))
        rows.append({"header_start": position, "header_end": newline, "body_start": newline + 1,
                     "body_end": body_end, "end": end, "body": command[newline + 1:body_end],
                     "terminated": closing is not None, "delimiter": found["delimiter"],
                     "quoted": bool(found["quote"]), "strip_tabs": bool(found["tabs"])})
        position = end
    return rows


def _segments(command, heredocs):
    endings = {row["header_end"]: row for row in heredocs}
    rows, start, index, quote, escaped, depth = [], 0, 0, None, False, 0
    def add(end):
        nonlocal start
        left, right = start, end
        while left < right and command[left].isspace():
            left += 1
        while right > left and command[right - 1].isspace():
            right -= 1
        if left < right:
            rows.append({"start": left, "end": right, "text": command[left:right]})
    while index < len(command):
        if index in endings and quote is None:
            end = endings[index]["end"]
            add(end)
            start, index = end, end
            continue
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\" and quote != "'":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif not depth and (char in ";\n" or command[index:index + 2] in {"&&", "||"}):
            add(index)
            index += 1 if command[index:index + 2] in {"&&", "||"} else 0
            start = index + 1
        index += 1
    add(len(command))
    return rows


def _tokens(text):
    try:
        lexer = shlex.shlex(text.split("\n", 1)[0], posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


def _patch_paths(patch):
    paths = []
    for line in patch.splitlines():
        if line.startswith("+++ ") and line[4:] != "/dev/null":
            try:
                name = shlex.split(line[4:])[0] if line[4:].startswith('"') else line[4:].split("\t", 1)[0]
            except (ValueError, IndexError):
                continue
            name = name[2:] if name.startswith("b/") else name
            path = _path(name)
            if path and _test_path(path):
                paths.append(path)
    return list(dict.fromkeys(paths))


def _terminal_files(value):
    complete = True
    if isinstance(value, dict) and "files" in value and isinstance(value["files"], list):
        complete = not value.get("errors") and value.get("complete", True) is not False
        value = value["files"]
    if isinstance(value, dict):
        value = [{"path": path, **({"content": row} if isinstance(row, str) else row)} for path, row in value.items()]
    if not isinstance(value, list):
        raise ValueError("terminal_files_require_metadata_list_or_path_mapping")
    result = {}
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid_terminal_file_metadata")
        path = _path(row.get("path", row.get("subject_path")))
        if path:
            if path in result:
                raise ValueError("duplicate_terminal_inventory_path")
            result[path] = dict(row)
    return result, complete


def _python_writes(body, cwd):
    """Literal Path/open writes only; never evaluate or execute subject code."""
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return []
    rows, handles = [], {}
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    def literal_write(node, content):
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try,
                                    ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                return None
            current = parents.get(current)
        return content
    def opened(node):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open"
                and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
            mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            if isinstance(mode, str) and any(flag in mode for flag in "wax"):
                return _path(node.args[0].value, cwd), mode
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                info = opened(item.context_expr)
                if info and isinstance(item.optional_vars, ast.Name):
                    handles[item.optional_vars.id] = info
    for node in ast.walk(tree):
        if (not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute)
                or node.func.attr not in {"write_text", "write_bytes", "write"} or not node.args):
            continue
        owner = node.func.value
        if node.func.attr == "write":
            info = handles.get(owner.id) if isinstance(owner, ast.Name) else opened(owner)
            if info and info[0]:
                content = node.args[0].value if isinstance(node.args[0], ast.Constant) and "a" not in info[1] else None
                rows.append((info[0], literal_write(node, content if isinstance(content, str) else None), "literal_python_open_write"))
            continue
        if not isinstance(owner, ast.Call) or not owner.args:
            continue
        name = owner.func.id if isinstance(owner.func, ast.Name) else owner.func.attr if isinstance(owner.func, ast.Attribute) else None
        if name != "Path" or not isinstance(owner.args[0], ast.Constant) or not isinstance(owner.args[0].value, str):
            continue
        path = _path(owner.args[0].value, cwd)
        if path:
            content = node.args[0].value if isinstance(node.args[0], ast.Constant) else None
            if isinstance(content, bytes):
                try:
                    content = content.decode("utf-8")
                except UnicodeDecodeError:
                    content = None
            rows.append((path, literal_write(node, content if isinstance(content, str) else None), "literal_python_path_write"))
    # Multiple writes/append operations are not a complete-file byte oracle.
    return [(path, content if sum(other == path for other, _, _ in rows) == 1 else None, source)
            for path, content, source in rows]


def _validation_content(body, kind):
    if not body:
        return False
    if kind.startswith("python"):
        try:
            tree = ast.parse(body)
        except SyntaxError:
            return False
        return any(isinstance(node, ast.Assert) or isinstance(node, ast.Call)
                   and _VALIDATION.search(ast.unparse(node.func)) for node in ast.walk(tree))
    # Code stored inside string literals is not evidence that its writer itself
    # performs validation. The extracted historical file retains those bytes.
    without_literals = re.sub(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|`(?:\\.|[^`\\])*`", "''", body)
    return bool(_VALIDATION.search(without_literals))


def _writes(segment, tokens, heredoc, cwd):
    rows = []
    header = segment["text"].split("\n", 1)[0]
    for match in re.finditer(r"(?<![<>])(?P<append>>>|>)\s*(?P<path>'[^']+'|\"[^\"]+\"|[^\s;&|<>]+)", header):
        try:
            token = shlex.split(match["path"])[0]
        except (ValueError, IndexError):
            continue
        path = _path(token, cwd)
        if not path:
            continue
        # Numeric stream destinations and /dev/null are not source material.
        if token.isdigit() or token.startswith("&"):
            continue
        content = heredoc["body"] if heredoc and tokens and posixpath.basename(tokens[0]) == "cat" and match["append"] == ">" else None
        if content is not None and heredoc["strip_tabs"]:
            content = "".join(line.lstrip("\t") for line in content.splitlines(keepends=True))
        if content is not None and not heredoc["quoted"] and any(char in content for char in "$`\\"):
            content = None
        rows.append((path, content, "shell_redirection_write"))
    if tokens and posixpath.basename(tokens[0]) == "tee":
        rows += [(path, heredoc["body"] if heredoc and "-a" not in tokens else None, "tee_write")
                 for token in tokens[1:] if not token.startswith("-") and (path := _path(token, cwd))]
    if tokens and posixpath.basename(tokens[0]) in {"sed", "perl"} and any(token.startswith("-i") for token in tokens):
        rows += [(path, None, "in_place_text_edit") for token in tokens[1:] if token.endswith(_SCRIPT_EXTENSIONS)
                 and (path := _path(token, cwd))]
    if tokens and posixpath.basename(tokens[0]) in {"cp", "mv"}:
        arguments = [token for token in tokens[1:] if not token.startswith("-")]
        if len(arguments) == 2 and arguments[-1].endswith(_SCRIPT_EXTENSIONS):
            path = _path(arguments[-1], cwd)
            if path:
                rows.append((path, None, "copied_or_moved_authored_candidate"))
    if heredoc and tokens and posixpath.basename(tokens[0]) == "apply_patch":
        for match in re.finditer(r"^\*\*\* (?:Add|Update) File: (.+)$", heredoc["body"], re.M):
            path = _path(match[1], cwd)
            if path:
                rows.append((path, None, "apply_patch_source_edit"))
    if tokens and re.fullmatch(r"python(?:[23](?:\.\d+)?)?", posixpath.basename(tokens[0])):
        body = heredoc["body"] if heredoc else tokens[tokens.index("-c") + 1] if "-c" in tokens and tokens.index("-c") + 1 < len(tokens) else None
        if body is not None:
            rows += _python_writes(body, cwd)
    return rows


def _unwrap(tokens):
    tokens = list(tokens)
    while tokens and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", tokens[0]):
        tokens.pop(0)
    if tokens and posixpath.basename(tokens[0]) == "env":
        tokens.pop(0)
        while tokens and (tokens[0].startswith("-") or "=" in tokens[0]):
            tokens.pop(0)
    if tokens and posixpath.basename(tokens[0]) == "timeout":
        tokens.pop(0)
        while tokens and tokens[0].startswith("-"):
            tokens.pop(0)
        if tokens:
            tokens.pop(0)
    if tokens and tokens[0] in {"npx", "pnpm", "yarn", "bunx"} and len(tokens) > 1 and tokens[1] in {"tsx", "jest", "vitest", "mocha"}:
        tokens.pop(0)
    return tokens


def _runner(tokens, heredoc):
    tokens = _unwrap(tokens)
    if not tokens:
        return None
    name, rest = posixpath.basename(tokens[0]), tokens[1:]
    if name in {"pytest", "py.test", "jest", "vitest", "mocha"}:
        return {"kind": name, "suite": True, "arguments": rest}
    if re.fullmatch(r"python(?:[23](?:\.\d+)?)?", name):
        if len(rest) > 1 and rest[0] == "-m" and rest[1] in {"pytest", "unittest"}:
            return {"kind": rest[1], "suite": True, "arguments": rest[2:]}
        return {"kind": "python_inline" if heredoc or "-c" in rest else "python_script", "suite": False, "arguments": rest}
    if name == "go" and rest and rest[0] in {"test", "run"}:
        return {"kind": "go_" + rest[0], "suite": rest[0] == "test", "arguments": rest[1:]}
    if name in {"node", "nodejs", "tsx", "ts-node", "deno", "bun"}:
        return {"kind": name + ("_inline" if heredoc else "_test" if "--test" in rest or rest[:1] == ["test"] else "_script"),
                "suite": "--test" in rest or rest[:1] == ["test"], "arguments": rest}
    if name in {"npm", "pnpm", "yarn", "make", "cargo"} and any(re.search(r"test|check|validat", arg, re.I) for arg in rest):
        return {"kind": "delegated_" + name, "suite": True, "arguments": rest}
    if name in {"bash", "sh"}:
        return {"kind": "shell_inline" if heredoc else "shell_script", "suite": False, "arguments": rest}
    if tokens[0].startswith(("./", "/tmp/", "/app/")):
        return {"kind": "custom_executable", "suite": False, "arguments": tokens[:1]}
    return None


def _suite_language_matches(path, kind):
    if kind == "go_test":
        return path.endswith("_test.go")
    if kind in {"pytest", "unittest"}:
        return path.endswith(".py")
    if kind in {"jest", "vitest", "mocha", "node_test", "nodejs_test", "tsx_test", "ts-node_test",
                "deno_test", "bun_test", "delegated_npm", "delegated_pnpm", "delegated_yarn"}:
        return path.endswith((".js", ".cjs", ".mjs", ".ts", ".tsx", ".jsx"))
    return True


def build_validation_inventory(trajectory, patch: str, terminal_files) -> dict:
    """Enumerate validation candidates from all raw calls, never a selected target.

    ``terminal_files`` accepts a filesystem-inventory dict, metadata list, or
    absolute-path -> metadata/text mapping. Returned terminal content is exactly
    supplied text; missing metadata never causes historical text to be overlaid.
    ``all_authored_test_paths`` includes explicitly executed authored files and
    suite-membership candidates. ``terminal_authored_test_paths`` is the export
    allowlist restricted to present terminal files. Collection and command
    legality remain explicit review obligations for every candidate.
    """
    if not isinstance(patch, str):
        raise ValueError("patch_must_be_text")
    terminal, complete_inventory = _terminal_files(terminal_files)
    authored = {path: [{"source": "final_patch_test_change", "call_id": None,
                       "execution_order_unknown": True}] for path in _patch_paths(patch)}
    versions, files, groups, unknown, nonvalidation = {}, {}, {}, [], []
    parsed = _calls(trajectory)
    if len({row["id"] for row in parsed}) != len(parsed):
        raise ValueError("duplicate_raw_call_id")
    for ordinal, action in enumerate(parsed):
        command = action["command"]
        if command is None or action.get("function") not in {"bash", "shell", "terminal"}:
            unknown.append({"call_id": action["id"], "reason": "unsupported_raw_tool_or_missing_shell_command",
                            "needs_manual_command_review": True, "command": command})
            continue
        heredocs = _heredocs(command)
        segments = _segments(command, heredocs)
        cwd, action_writes, action_instances = "/app", [], []
        for index, segment in enumerate(segments):
            tokens = _tokens(segment["text"])
            heredoc = next((row for row in heredocs if segment["start"] <= row["header_end"] < segment["end"]), None)
            if tokens and tokens[0] == "cd" and len(tokens) == 2:
                target = _path(tokens[1], cwd)
                cwd = target or (tokens[1] if tokens[1] in {"/app", "/tmp"} else None)
                nonvalidation.append({"call_id": action["id"], "segment": index, "kind": "working_directory_change"})
                continue
            if cwd is None:
                unknown.append({"call_id": action["id"], "command": segment["text"], "reason": "working_directory_unresolved",
                                "needs_manual_command_review": True})
                continue
            writes = _writes(segment, tokens, heredoc, cwd)
            for path, content, source in writes:
                record = {"source": source, "call_id": action["id"], "segment": index,
                          "command_offsets": [segment["start"], segment["end"]], "path": path}
                authored.setdefault(path, []).append(record)
                versions[path] = {**record, "content": content, "sha256": _sha(content) if content is not None else None}
                action_writes.append(path)
            runner = _runner(tokens, heredoc)
            if runner is None:
                base = posixpath.basename(tokens[0]) if tokens else ""
                if writes or base in {"cat", "echo", "printf", "ls", "pwd", "git", "find", "rg", "grep", "sed", "head", "tail", "rm", "mkdir", "chmod", "set", "export", "true", "false", "sleep", "exit"}:
                    nonvalidation.append({"call_id": action["id"], "segment": index,
                                          "kind": "authoring_or_nonrunner_shell_segment", "command": segment["text"]})
                else:
                    unknown.append({"call_id": action["id"], "segment": index, "command": segment["text"],
                                    "command_offsets": [segment["start"], segment["end"]],
                                    "reason": "unrecognized_command_requires_validation_relevance_review",
                                    "needs_manual_command_review": True})
                continue
            args = runner["arguments"]
            explicit = []
            for argument in args:
                path = _path(argument, cwd) if not argument.startswith("-") else None
                if path and (path in authored or argument.split("::", 1)[0].endswith(_SCRIPT_EXTENSIONS)):
                    explicit.append(path)
            explicit = list(dict.fromkeys(explicit))
            candidates = [path for path in explicit if path in authored]
            binding = "explicit_file_invocation"
            if runner["suite"]:
                selectors = [arg.split("::", 1)[0] for arg in args if not arg.startswith("-")
                             and ("/" in arg or arg.startswith(".") or arg.endswith(_SCRIPT_EXTENSIONS)
                                  or any(path.startswith((_path(arg, cwd) or "<unresolved>").rstrip("/") + "/") for path in authored))]
                for path in authored:
                    if not _test_path(path) or not _suite_language_matches(path, runner["kind"]):
                        continue
                    relevant = not selectors
                    for selector in selectors:
                        prefix = _path(selector.removesuffix("/..."), cwd)
                        if prefix and (path == prefix or path.startswith(prefix.rstrip("/") + "/") or fnmatch.fnmatch(path, prefix)):
                            relevant = True
                        if selector in {".", "./..."} and path.startswith(cwd.rstrip("/") + "/"):
                            relevant = True
                    if relevant and path not in candidates:
                        candidates.append(path)
                binding = "suite_membership_candidates_collection_unverified"
            inline = bool(heredoc and runner["kind"] != "shell_script") or runner["kind"] == "python_inline"
            inline_body = heredoc["body"] if heredoc else tokens[tokens.index("-c") + 1] if runner["kind"] == "python_inline" and "-c" in tokens and tokens.index("-c") + 1 < len(tokens) else None
            validation_content = _validation_content(inline_body, runner["kind"])
            if inline and writes and not validation_content:
                unknown.append({"call_id": action["id"], "segment": index, "command": segment["text"],
                                "reason": "inline_authoring_script_not_established_as_validation",
                                "needs_manual_command_review": True})
                continue
            last_segment = index == len(segments) - 1
            suffix = command[segment["start"]:] if last_segment else None
            production_prefix = [path for path in action_writes if not _test_path(path) and not path.startswith("/tmp/")]
            reasons = ["shell_extraction_does_not_establish_safety_or_test_collection"]
            if binding.startswith("suite_"):
                reasons.append("suite_membership_requires_collection_confirmation")
            if production_prefix:
                reasons.append("mixed_action_contains_production_writes")
            if not last_segment:
                reasons.append("invocation_is_not_a_standalone_terminal_suffix")
            if "&&" in command[:segment["start"]] or "||" in command[:segment["start"]]:
                reasons.append("conditional_reachability_requires_execution_evidence")
            if "|" in segment["text"].split("\n", 1)[0]:
                reasons.append("pipeline_shell_status_is_not_test_verdict")
            if inline and not validation_content:
                reasons.append("inline_script_validation_role_unresolved")
            if heredoc and not heredoc["terminated"]:
                reasons.append("unterminated_heredoc")
            if heredoc and not heredoc["quoted"] and any(char in heredoc["body"] for char in "$`\\"):
                reasons.append("heredoc_shell_expansion_requires_review")
            instance = {"call_id": action["id"], "segment": index, "trajectory_ordinal": ordinal,
                        "command_offsets": [segment["start"], segment["end"]],
                        "working_directory": cwd, "command_segment": segment["text"],
                        "exact_test_only_command_suffix": suffix,
                        "suffix_offset": segment["start"] if suffix is not None else None,
                        "shell_action_returncode": (action.get("expected") or {}).get("returncode")
                            if isinstance(action.get("expected"), dict) else None,
                        "production_write_paths_in_prefix_or_segment": production_prefix,
                        "file_versions_at_invocation": {path: versions.get(path) for path in candidates},
                        "needs_manual_command_review": True, "automatic_execution_allowed": False,
                        "review_reasons": reasons}
            key = json.dumps([runner["kind"], cwd, segment["text"], sorted(candidates)], separators=(",", ":"))
            identity = "validation_" + _sha(key)[:20]
            group = groups.setdefault(identity, {"id": identity, "kind": runner["kind"], "test_paths": sorted(candidates),
                "explicit_invoked_paths": explicit, "authorship_established": bool(candidates) or inline,
                "inline": inline, "inline_body": inline_body, "binding": binding, "executions": [],
                "needs_manual_command_review": True, "automatic_execution_allowed": False})
            group["executions"].append(instance)
            action_instances.append(instance)
            group["last_execution"] = instance
            group["execution_call_ids"] = list(dict.fromkeys(row["call_id"] for row in group["executions"]))
            for path in candidates:
                entry = files.setdefault(path, {"path": path, "execution_call_ids": [], "invocation_ids": [], "provenance": []})
                if action["id"] not in entry["execution_call_ids"]:
                    entry["execution_call_ids"].append(action["id"])
                if identity not in entry["invocation_ids"]:
                    entry["invocation_ids"].append(identity)
                entry["last_execution"] = instance
                entry["last_known_executed_version"] = versions.get(path)
        action_production = sorted(set(path for path in action_writes if not _test_path(path) and not path.startswith("/tmp/")))
        for instance in action_instances:
            instance["production_write_paths_in_action"] = action_production
            if action_production and "mixed_action_contains_production_writes" not in instance["review_reasons"]:
                instance["review_reasons"].append("mixed_action_contains_production_writes")
    for path, entry in files.items():
        entry["provenance"] = authored[path]
        current = terminal.get(path)
        present = current is not None and current.get("kind", "file") == "file" and current.get("status", "present") != "missing"
        entry["terminal_availability"] = ("present" if present else "unsupported_file_kind" if current and current.get("kind") not in {None, "file", "missing"}
            else "historical_only_missing_at_submission" if complete_inventory else "unresolved_inventory_incomplete")
        entry["terminal_metadata"] = current
        content = current.get("content") if present else None
        entry["terminal_text"] = content if isinstance(content, str) else None
        entry["terminal_text_requires_export"] = present and not isinstance(content, str)
        last = entry["last_known_executed_version"]
        terminal_sha = _sha(content) if isinstance(content, str) else current.get("sha256") if present else None
        entry["terminal_matches_last_known_executed_bytes"] = (terminal_sha == last["sha256"]
            if terminal_sha and last and last.get("sha256") else None)
        entry["historical_text"] = last.get("content") if last else None
        entry["needs_manual_command_review"] = True
        entry["validation_role"] = "test_file_or_temporary_script" if _test_path(path) or path.startswith("/tmp/") else "executed_authored_script_role_unresolved"
    invocations = list(groups.values())
    return {"version": "terminal-validation-inventory.v1", "tests": [files[path] for path in sorted(files)],
            "invocations": invocations, "unknown_commands": unknown, "nonvalidation_segments": nonvalidation,
            "all_authored_test_paths": sorted(files),
            "terminal_authored_test_paths": sorted(path for path, row in files.items() if row["terminal_availability"] == "present"),
            "historical_only_test_paths": sorted(path for path, row in files.items() if row["terminal_availability"] == "historical_only_missing_at_submission"),
            "patch_test_paths_without_matched_invocation": sorted(path for path in _patch_paths(patch) if path not in files),
            "inline_invocation_ids": [row["id"] for row in invocations if row["inline"]],
            "command_offset_unit": "Unicode codepoints; offsets slice the exact original Python command string",
            "raw_action_count": len(parsed), "deduplication": "Exact invocation text, runner kind, working directory and bound files; retain every call and the last execution/version.",
            "selection_policy": "All raw actions and authored test candidates; no Pilot 1 target, masking label, or repair outcome selection.",
            "execution_scope": "Raw shell action recorded as executed; branch reachability, collection, test role and command safety require review.",
            "historical_test_overlay_allowed": False}
