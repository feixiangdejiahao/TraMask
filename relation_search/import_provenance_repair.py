"""Recover a transported TypeScript import from its exact donor declaration.

Some historical constructors rebased a relative module and retained the donor
path. The emitter rebases it again. Repair only that provable metadata pattern;
unknown bindings remain explicit. This creates a new test requiring review.
"""
from __future__ import annotations

import copy
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import Source

VERSION = 'donor-import-provenance-repair.v1'


def _resolve(owner, module):
    if not module.startswith('.'):
        return ('package', module)
    path = posixpath.normpath(posixpath.join(posixpath.dirname(owner), module))
    if path == '..' or path.startswith('../') or path.startswith('/'):
        raise ValueError('Relative import escapes repository')
    return ('relative', path)


def _rebase(owner, module, target):
    kind, resolved = _resolve(owner, module)
    if kind == 'package':
        return module
    relative = posixpath.relpath(resolved, posixpath.dirname(target) or '.')
    return relative if relative.startswith('.') else './' + relative


def repair(corpus, candidate):
    result = copy.deepcopy(candidate)
    if corpus['language'] != 'typescript':
        return dict(status='not_applicable', candidate=result, changes=[], unresolved=[])
    target = corpus['tests'][candidate['base_test_id']]['span']['path']
    changes, unresolved = [], []
    for index, imported in enumerate(result.get('imports', [])):
        donor = imported.get('source_path')
        binding = imported.get('source_binding')
        if not donor or not binding:
            unresolved.append(dict(index=index, reason='no_exact_donor_binding_provenance'))
            continue
        record = corpus['sources'].get(donor)
        if not record:
            unresolved.append(dict(index=index, reason='donor_source_unavailable'))
            continue
        source = Source(donor, record['code'], 'typescript')
        declaration = source.imports.get(binding)
        if source.root.has_error or declaration is None:
            unresolved.append(dict(index=index, reason='donor_import_unavailable'))
            continue
        module, member = declaration
        if member != imported.get('imported_name'):
            unresolved.append(dict(index=index, reason='donor_imported_member_differs'))
            continue
        if module == imported['module']:
            continue
        if module.startswith('.') and _rebase(donor, module, target) == imported['module']:
            changes.append(dict(index=index, alias=imported['name'], donor_path=donor,
                donor_binding=binding, before=imported['module'], after=module,
                intended_module=_resolve(donor, module)[1],
                previous_emitted_module=_resolve(donor, imported['module'])[1],
                donor_source_sha256=hashlib.sha256(record['code'].encode()).hexdigest()))
            imported['module'] = module
        else:
            unresolved.append(dict(index=index, reason='not_the_known_double_rebase_pattern'))
    if changes:
        result['id'] = 'importfix_' + hashlib.sha256(json.dumps(
            dict(parent=candidate['id'], imports=result['imports']), sort_keys=True).encode()).hexdigest()[:24]
        result['import_provenance_repair'] = dict(version=VERSION, parent=candidate['id'], changes=changes,
            semantic_validity='unconfirmed', whole_test_review_required=True, native_reexecution_required=True)
    return dict(version=VERSION, status='repaired' if changes else 'unchanged',
                candidate=result, changes=changes, unresolved=unresolved)


def verify_bindings(corpus, candidate, emitted_path, emitted_code):
    """Check generated import identities independently of test-body ASTs."""
    if corpus['language'] != 'typescript':
        return dict(status='not_applicable')
    source = Source(emitted_path, emitted_code, 'typescript')
    if source.root.has_error:
        return dict(status='unknown', reason='emitted_source_parse_error')
    checks = []
    for row in candidate.get('imports', []):
        expected = (_resolve(row.get('source_path', emitted_path), row['module']), row.get('imported_name'))
        actual = source.imports.get(row['name'])
        resolved = (_resolve(emitted_path, actual[0]), actual[1]) if actual else None
        checks.append(dict(alias=row['name'], expected=expected, actual=resolved, matched=expected == resolved))
    return dict(status='matched' if all(row['matched'] for row in checks) else 'mismatch', checks=checks,
                scope='Explicit generated imports only; export availability and oracle validity remain separate.')
