"""Select command, observation and data carriers beside program slices."""
from pathlib import PurePosixPath

from .anchors import SUFFIXES
from .retrieval import observed_action_jobs

VALIDATION = {'validation_or_script', 'program_execution', 'subject_execution',
              'module_execution', 'authored_validation_fragment'}


def data_entries(files, mentioned, paths):
    """Keep explicit data files and snapshots beside matched source files."""
    directories = {PurePosixPath(path).parent for path in paths}
    result = []
    for file in files:
        path = PurePosixPath(file['path'])
        if path.suffix in SUFFIXES:
            continue
        if file['path'] in mentioned:
            reason = 'explicit_path'
        elif (path.suffix == '.snap' and path.parent.name in {'snapshots', '__snapshots__'}
              and path.parent.parent in directories):
            reason = 'adjacent_snapshot'
        else:
            continue
        result.append({'source': file['source'], 'path': file['path'], 'reason': reason})
    return result


def select_material_entries(actions, names, changes, paths, action_ids, files):
    """Use source provenance, validation roles and structured read payloads.

    Actions are original recorded commands/observations. Returned entries are
    addresses, not copies of their text or inferred program-dependency edges.
    """
    rules = [{'calls': names, 'types': [], 'fields': [], 'input_tokens': []}]
    jobs = observed_action_jobs(actions, rules, list(changes))
    by_id = {action['id']: action for action in actions}
    selected = {identity: {'matched_source'} for identity in action_ids}
    mentioned = set()
    for job in jobs:
        reasons = set()
        if paths.intersection(job['paths']):
            reasons.add('matched_path')
        if VALIDATION.intersection(job['roles']):
            reasons.add('validation_or_execution')
        if 'structured_read' in job['roles']:
            reasons.add('structured_read')
        if reasons:
            selected.setdefault(job['action_id'], set()).update(reasons)
        if job['action_id'] in selected:
            mentioned.update(job['paths'])
    return {'actions': [{'action': identity, 'reasons': sorted(selected[identity])}
                        for identity in by_id if identity in selected],
            'files': data_entries(files, mentioned, paths | mentioned)}
