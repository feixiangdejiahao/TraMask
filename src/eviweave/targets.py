"""Step D: select pre-slice entries and carry B's complete workset forward."""
from collections import defaultdict
from pathlib import Path, PurePosixPath

from .anchors import SUFFIXES, changed_lines, parse_source
from .artifacts import read_json,read_manifest
from .history import materials_from_manifest, material_records, read_context
from .invocations import commands
from .retrieval import retrieve_entries
from .shell import inline_sources


def locate_targets(issue, patch, materials, submitted, authored_versions):
    """Select from issue/Patch and historical provenance, without choosing a test.

    authored_versions contains file versions changed since A's initial snapshot.
    Literal writes and inline scripts also retain their original command source.
    Positions address UTF-8 bytes of read_target_source(), including decoded
    command literals and Python files with a declared source encoding.
    """
    sources, origins, errors, parsed = [], {}, [], {}

    def add(material, path, text, kind, role='file', index=0):
        raw = text.encode()
        key = PurePosixPath(path).suffix, raw
        if key not in parsed:
            parsed[key] = parse_source(path, raw)
        identity = material['source'] + ':' + role + ':' + str(index)
        origin = {'source': material['source']}
        if role != 'file':
            origin[role] = index
        source = {'id': identity, 'path': path, 'raw': raw, 'kind': kind, 'parsed': parsed[key]}
        sources.append(source)
        origins[identity] = origin
        if parsed[key]['parse_errors']:
            errors.append({**origin, 'errors': parsed[key]['parse_errors']})
        return source

    actions = [{'id': m['action_id'], 'command': m['text'], 'expected': m['expected']}
               for m in materials if m['kind'] == 'command']
    discovery = commands(actions)
    writes = defaultdict(list)
    for write in discovery['source_literals']:
        writes[write['action_id']].append(write)
    command_sources = {m['action_id']: m['source'] for m in materials if m['kind'] == 'command'}
    for error in discovery['issues']:
        errors.append({'source': command_sources[error['action_id']], 'errors': [
            {'kind': 'source_command', 'message': error['reason'], 'segment': error['segment']}]})
    changed, found, final = changed_lines(patch), set(), []
    for material in materials:
        if material['kind'] == 'file' and PurePosixPath(material['path']).suffix in SUFFIXES:
            if 'source_error' in material:
                errors.append({'source': material['source'], 'errors': [
                    {'kind': 'source_encoding', 'message': material['source_error']}]})
                continue
            kind = ('historical_write' if (material['path'], material['sha256']) in authored_versions
                    else 'repository_file')
            source = add(material, material['path'], material['text'], kind)
            relative = material['path'].removeprefix('/app/')
            if relative in changed and submitted.get(material['path']) == material['sha256']:
                final.append(source)
                found.add(relative)
        elif material['kind'] == 'command':
            for index, write in enumerate(writes[material['action_id']]):
                if PurePosixPath(write['path']).suffix in SUFFIXES:
                    add(material, write['path'], write['content'], 'historical_write', 'write', index)
            extraction = inline_sources(material['text'])
            for index, source in enumerate(extraction['sources']):
                add(material, source['path'], source['text'], 'inline_script', 'inline', index)
            if extraction['issues']:
                errors.append({'source': material['source'], 'errors': extraction['issues']})
    result = retrieve_entries(issue, changed, final, sources, actions)
    selected, by_source = result['selection'], {s['id']: s for s in sources}
    unit_indices = {(u['source'], u['start'], u['end']): i for i, u in enumerate(selected['units'])}
    units = [{**u, **origins[u['source']], 'path': by_source[u['source']]['path']} for u in selected['units']]
    coarse={u['source'] for u in selected['units'] if [u['start'],u['end']] in u['anchors']}
    queries=defaultdict(set)
    for (source,_,_),matches in result['local_queries'].items():
        if source in coarse:queries[source].update((a,b) for _,_,a,b in matches)
    return {'targets': result['targets'], 'records': material_records(materials), 'units': units,
            'local_queries': [{**origins[source],'points':[list(p) for p in sorted(points)]} for source,points in sorted(queries.items())],
            'changed_paths':sorted(changed),
            'syntax_templates': [[unit_indices[tuple(key)] for key in group] for group in selected['jobs']],
            'metrics': {key: result['metrics'][key] for key in (
                'root_units', 'anchor_positions', 'units_with_support', 'source_bytes',
                'syntax_template_jobs', 'syntax_template_bytes')},
            'parse_errors': errors,
            'missing_patch_sources': sorted(path for path in changed
                                            if PurePosixPath(path).suffix in SUFFIXES and path not in found)}


def targets_from_manifest(manifest_path):
    """Run D on all collected sources from an A replay with a validated submission."""
    manifest_path = Path(manifest_path).resolve()
    manifest=read_manifest(manifest_path)
    trajectory=read_json(manifest['trajectory']) if 'trajectory' in manifest else None
    materials=materials_from_manifest(manifest_path,manifest,trajectory)
    return targets_from_collection(manifest_path, manifest, materials, trajectory)


def targets_from_collection(manifest_path, manifest, materials, trajectory):
    """Select D candidates from the collection already loaded by the pipeline."""
    if not manifest['submission_state_validated']:
        raise ValueError('Step D requires a replay with a validated submission state')
    inputs = Path(manifest['replay']) / 'inputs'
    initial = read_json(manifest_path.parent / 'snapshots/initial.json')
    snapshot = read_json(manifest_path.parent / 'snapshots/submission.json')
    initial_versions = {(r['path'], r['sha256']) for r in initial['files'] if r['kind'] == 'file'}
    authored = {(m['path'], m['sha256']) for m in materials if m['kind'] == 'file'} - initial_versions
    if trajectory is not None:
        authored={(m['path'],m['sha256']) for m in trajectory['materials'].values()
                  if m['kind'] in {'file','code_input'} and m['producer'] is not None}
    submitted = {r['path']: r['sha256'] for r in snapshot['files'] if r['kind'] == 'file'}
    result = locate_targets((inputs / 'instruction.md').read_text(), (inputs / 'model.patch').read_text(),
                            materials, submitted, authored)
    return {'manifest': str(manifest_path), **result}


def read_target_source(unit, *, base=None):
    """Read a unit's complete file or decoded command source, before case scoping."""
    text = read_context(unit['source'],base=base)
    if 'inline' in unit:
        return inline_sources(text)['sources'][unit['inline']]['text']
    if 'write' in unit:
        return commands([{'id': 'source', 'command': text}])['source_literals'][unit['write']]['content']
    return text
