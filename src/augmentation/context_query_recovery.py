"""Uniform recovery for source-search queries whose path names a directory.

The frozen v1 accepted file paths but its prompt did not restrict search paths
to files. This adapter changes only that transport behavior; no task-specific
targets, gold sources or semantic rules are introduced.
"""
from pathlib import Path

from augmentation import validation_context_pilot as original


def directory_members(case, base, query):
    if not isinstance(query, dict) or query.get("kind") != "search" or not query.get("path"):
        return None
    path = Path(str(query["path"]))
    if path.is_absolute() or ".." in path.parts or any(p in original.EXCLUDED or p.startswith(".env") for p in path.parts):
        return None
    root = Path(case["repository"]).resolve()
    directory = (root/path).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        return None
    prefix = str(path).rstrip("/")+"/" if str(path) != "." else ""
    return [p for p in base["source_file_index"] if p.startswith(prefix)]


def serve_queries(case, base, events, queries, *, history_allowed):
    answers = []
    for query in queries[:6] if isinstance(queries, list) else []:
        members = directory_members(case, base, query)
        if members is None:
            answers.extend(original.serve_queries(case, base, events, [query], history_allowed=history_allowed))
            continue
        text = query.get("text", "")
        if not isinstance(text, str) or not text or len(text) > 200:
            answers.append({"query": query, "error": "invalid_literal_search"})
            continue
        matches = []
        for path in members:
            source = original.public_file(case["repository"], path)
            for i, line in enumerate(source.read_text(errors="replace").splitlines()):
                if text in line:
                    matches.append({"path": path, "line": i+1, "text": line[:800]})
                    if len(matches) == 40:
                        break
            if len(matches) == 40:
                break
        answers.append({"query": query, "answer": {"matches": matches, "cap": 40, "literal_search": True,
                        "directory_scope": query["path"]}})
    return answers
