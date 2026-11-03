"""JSON artifacts and content identities shared by replay and analysis."""
import hashlib
import json
import os
from pathlib import Path


def read_json(path):
    return json.loads(Path(path).read_bytes())


def read_manifest(path):
    """Resolve a collection's relative references at its input boundary."""
    path = Path(path).resolve()
    manifest = read_json(path)
    manifest['replay'] = str((path.parent / manifest['replay']).resolve())
    if 'trajectory' in manifest:
        manifest['trajectory'] = str((path.parent / manifest['trajectory']).resolve())
    return manifest


def reference_path(reference, base):
    filename, separator, fragment = reference.partition('#')
    return str((Path(base) / filename).resolve()) + separator + fragment


def _map_references(value, transform):
    """Transform only source fields in the exported A/B/D/F schemas."""
    if isinstance(value, list):
        return [_map_references(v, transform) for v in value]
    if isinstance(value, dict):
        result = dict(value)
        for key in ('source', 'manifest', 'trajectory'):
            if key in value:
                item = value[key]
                result[key] = transform(item) if isinstance(item,str) else _map_references(item,transform)
        for key in ('records', 'units', 'parse_errors', 'pending_roots', 'files', 'material_entries', 'local_queries'):
            if key in value:result[key] = _map_references(value[key],transform)
        return result
    return value


def relative_references(value, base):
    """Write source references relative to the exported artifact directory."""
    def relative(reference):
        filename, separator, fragment = reference.partition('#')
        return os.path.relpath(filename, base) + separator + fragment
    return _map_references(value, relative)


def resolve_references(value, base):
    """Resolve the source references in one exported artifact."""
    return _map_references(value, lambda reference: reference_path(reference,base))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def file_ref(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
