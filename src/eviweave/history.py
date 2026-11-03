"""Step B: searchable text with one reference to existing Step A material."""
from pathlib import Path

from .artifacts import read_json, read_manifest, reference_path
from .blobs import BlobStore
from .source_text import decode_material


def window_spans(text, window_chars):
    """Line-aware windows shared with the original retrieval pilot."""
    assert window_chars > 0
    start = 0
    while start < len(text):
        end = min(start + window_chars, len(text))
        newline = text.rfind('\n', start + window_chars // 2, end)
        if end < len(text) and newline >= 0:
            end = newline + 1
        yield start, end
        start = end


def read_context(source, *, base=None):
    """Read the complete saved material addressed by a history record.

    Sources are absolute file paths, JSON string fields (#/output), or entries
    in A's file/candidate arrays (#/source_versions/0). Array entries point to
    A's existing blob; head/tail fields return only the originally saved part.
    No new source metadata is stored by B.
    """
    if base is not None:source=reference_path(source,base)
    filename, _, fragment = source.partition('#')
    path = Path(filename)
    if not fragment:
        return path.read_bytes().decode('utf-8')
    parts = fragment.removeprefix('/').split('/')
    value = read_json(path)
    if len(parts) == 1:
        return value[parts[0]]
    collection, index = parts
    entry = value[collection][index if collection=='materials' else int(index)]
    raw = BlobStore(path.parent / 'blobs').read(entry['sha256'])
    text, error = decode_material(entry['path'], raw)
    if text is None:
        raise ValueError('Source text cannot be decoded: ' + error)
    return text


def read_source_bytes(source, *, base=None):
    """Read the original bytes of an A file source, including undecodable files."""
    if base is not None:source=reference_path(source,base)
    filename, _, fragment = source.partition('#')
    path = Path(filename)
    if not fragment:
        return path.read_bytes()
    collection, index = fragment.removeprefix('/').split('/')
    entry = read_json(path)[collection][index if collection=='materials' else int(index)]
    return BlobStore(path.parent / 'blobs').read(entry['sha256'])


def load_materials(manifest_path):
    """Read A's textual materials once, retaining paths for source parsing.

    These in-memory entries describe existing A material. B exports only
    id/text/source; D also uses path, kind and file digest to select a grammar
    and distinguish source versions. Commands carry the existing action ID
    and original observations for D's historical scope and write extraction.
    Binary fixtures remain in A. Missing artifacts propagate.
    """
    manifest_path = Path(manifest_path).resolve()
    manifest = read_manifest(manifest_path)
    trajectory=read_json(manifest['trajectory']) if 'trajectory' in manifest else None
    return manifest, materials_from_manifest(manifest_path, manifest, trajectory)


def materials_from_manifest(manifest_path, manifest, trajectory):
    """Read B material from an already parsed collection descriptor."""
    manifest_path = Path(manifest_path)
    replay = Path(manifest['replay'])
    plan = read_json(replay / 'plan.json')
    materials = []

    for collection in ('source_versions', 'unobserved_source_candidates'):
        for index, entry in enumerate(manifest[collection]):
            source = str(manifest_path) + '#/' + collection + '/' + str(index)
            try:
                raw = BlobStore(manifest_path.parent / 'blobs').read(entry['sha256'])
                text, error = decode_material(entry['path'], raw)
            except UnicodeDecodeError:
                continue
            material = {'source': source, 'text': text, 'kind': 'file',
                        'path': entry['path'], 'sha256': entry['sha256']}
            if error is not None:
                material['source_error'] = error
            materials.append(material)
    for action_id in plan['action_ids']:
        directory = replay / 'runtime/calls' / action_id
        command = (directory / 'command.sh').resolve()
        expected_path = (directory / 'archived_expected.json').resolve()
        expected = read_json(expected_path)
        materials.append({'source': str(command), 'text': command.read_bytes().decode('utf-8'),
                          'kind': 'command', 'action_id': action_id, 'expected': expected})
        for field in ('output', 'output_head', 'output_tail'):
            if field in expected:
                materials.append({'source': str(expected_path) + '#/' + field,
                                  'text': expected[field], 'kind': 'output', 'action_id': action_id})
        output = (directory / 'output.bin').resolve()
        try:
            text = output.read_bytes().decode('utf-8')
        except UnicodeDecodeError:
            continue
        materials.append({'source': str(output), 'text': text, 'kind': 'output', 'action_id': action_id})
    if trajectory is not None:
        graph_path=Path(manifest['trajectory'])
        for identity,entry in trajectory['materials'].items():
            if entry['kind'] not in {'stream','code_input'}:continue
            source=str(graph_path)+'#/materials/'+identity
            raw=BlobStore(graph_path.parent/'blobs').read(entry['sha256'])
            try:text=raw.decode('utf-8')
            except UnicodeDecodeError:continue
            material={'source':source,'text':text,'kind':'output','action_id':None}
            if entry['kind']=='code_input':material.update(kind='file',path=entry['path'],sha256=entry['sha256'])
            materials.append(material)
    return materials


def material_records(materials, *, window_chars=6000):
    """Keep every source context when splitting materials into B records."""
    records, seen = [], set()
    for material in materials:
        if material['text'] is None:
            continue
        for start, end in window_spans(material['text'], window_chars):
            chunk = material['text'][start:end]
            key = (material['source'], chunk)
            if chunk.strip() and key not in seen:
                records.append({'id': 'R' + str(len(records) + 1).zfill(4),
                                'text': chunk, 'source': material['source']})
                seen.add(key)
    return records


def history_records(manifest_path, *, window_chars=6000):
    """Build B's complete id/text/source workset; run no replay or model."""
    _, materials = load_materials(manifest_path)
    return material_records(materials, window_chars=window_chars)
