"""Expose source-proved implicit import names to the existing Go materializer."""
import hashlib
import json

from anchor_retrieval.syntax import Source, child, walk
from scripts.go_history_dependencies_v6 import _package_sources


def explicit_dependency_imports(files, inventory):
    packages = _package_sources(inventory)
    output, records = dict(files), []
    for path, code in files.items():
        if not path.endswith('.go'):
            continue
        source = Source(path, code, 'go')
        edits = []
        for node in walk(source.root):
            if node.type != 'import_spec' or child(node, 'name') is not None:
                continue
            literal = child(node, 'path')
            if literal is None:
                continue
            raw = source.text(literal)
            try:
                module = raw[1:-1] if raw.startswith('`') else json.loads(raw)
            except ValueError:
                continue
            package = packages.get(module)
            if not package:
                continue
            before = source.text(node)
            after = package['name'] + ' ' + before
            edits.append((node.start_byte, node.end_byte, before, after))
            records.append({'kind': 'source_proved_explicit_import_alias', 'path': path,
                            'module': module, 'name': package['name'],
                            'start_byte': node.start_byte, 'end_byte': node.end_byte,
                            'before': before, 'after': after,
                            'source_sha256': hashlib.sha256(code.encode()).hexdigest(),
                            'package_source_evidence': package['source_evidence'],
                            'initialization_preserved': True})
        data = code.encode()
        for start, end, before, after in sorted(edits, reverse=True):
            assert data[start:end].decode() == before
            data = data[:start] + after.encode() + data[end:]
        output[path] = data.decode()
    return output, records
