"""Uniform I/O repair replay of the frozen automatic-augmentation cohort.

No outcome is an input. Every original batch/arm/repetition is rerun. Short
identifiers, one exact wrapper cleanup and a 64K response channel are the only
changes to the model protocol; original semantic systems and executor remain.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research_tools import automatic_augmentation_provider as provider
from scripts import run_automatic_augmentation_pilot as original

VERSION = 'automatic-augmentation-io-repair.v2'
DEFAULT_ORIGINAL = ROOT / 'results/automatic_augmentation_pilot_20261005'
DEFAULT_OUTPUT = DEFAULT_ORIGINAL / 'io_repair_v2'
read, write, receipt, verify = original.read, original.write, original.receipt, original.verify
canonical, digest, evidence_ids = original.canonical, original.digest, original.evidence_ids
JUDGMENT_SYSTEM, GENERATION_SYSTEM = original.JUDGMENT_SYSTEM, original.GENERATION_SYSTEM
ARMS, REPEATS = list(original.ARMS), original.REPEATS

# These fields carry program or human-language content, never references to
# our transport identifiers. Exact string replacement cannot touch them.
PROTECTED_FIELDS = frozenset({
    'original_test', 'rewritten_test', 'text', 'code', 'public_issue', 'submitted_patch',
    'public_step', 'command', 'message', 'content', 'scope', 'reason',
    'existing_validation', 'missing_relation', 'preconditions', 'object_binding',
    'operations', 'observation', 'expectation', 'oracle_basis', 'missing_evidence',
    'base_test_id',
})
REFERENCE_FIELDS = frozenset({'seed_alias', 'seed_aliases', 'evidence_id',
                              'evidence_ids', 'step_evidence_ids'})


def replace_references(value, mapping, *, field=None):
    if field in PROTECTED_FIELDS:
        return value
    if isinstance(value, str):
        return mapping.get(value, value) if field in REFERENCE_FIELDS else value
    if isinstance(value, list):
        return [replace_references(x, mapping, field=field) for x in value]
    if isinstance(value, dict):
        return {k: replace_references(v, mapping, field=k) for k, v in value.items()}
    return value


def protected_content(value, *, field=None, path=()):
    if field in PROTECTED_FIELDS:
        return [(list(path), value)]
    if isinstance(value, dict):
        return [item for k, v in value.items() for item in protected_content(v, field=k, path=(*path, k))]
    if isinstance(value, list):
        return [item for i, v in enumerate(value) for item in protected_content(v, path=(*path, i))]
    return []


def shorten_batch(source, history, candidates):
    prefix = dict(history)
    if prefix.pop('trajectory_evidence', None) is None or prefix != source:
        raise ValueError('original_pair_source_prefix_mismatch')
    aliases = [c['seed_alias'] for c in candidates]
    if len(aliases) != len(set(aliases)) or source['seeds'] != candidates:
        raise ValueError('original_candidate_identity_mismatch')
    source_ids = sorted(evidence_ids(source))
    history_ids = sorted(evidence_ids(history) - set(source_ids))
    if set(aliases).intersection(source_ids + history_ids):
        raise ValueError('overlapping_seed_and_evidence_identity')
    forward = {alias: 'S%03d' % (n + 1) for n, alias in enumerate(aliases)}
    forward.update({identifier: 'E%04d' % (n + 1) for n, identifier in enumerate(source_ids + history_ids)})
    reverse = {v: k for k, v in forward.items()}
    if len(reverse) != len(forward):
        raise ValueError('noninjective_identifier_map')
    src, hist = replace_references(source, forward), replace_references(history, forward)
    if replace_references(src, reverse) != source or replace_references(hist, reverse) != history:
        raise ValueError('identifier_mapping_not_reversible')
    if protected_content(src) != protected_content(source) or protected_content(hist) != protected_content(history):
        raise ValueError('identifier_mapping_changed_protected_content')
    restored = dict(hist); restored.pop('trajectory_evidence')
    if canonical(restored) != canonical(src):
        raise ValueError('short_pair_source_prefix_mismatch')
    for before, after in zip(candidates, src['seeds']):
        if before['base_test_id'] != after['base_test_id'] or before.get('original_test') != after.get('original_test'):
            raise ValueError('identifier_mapping_changed_program_identity')
    mapping = dict(version='reversible-short-identifiers.v1', forward=forward, reverse=reverse,
                   source_evidence_ids=source_ids, history_only_evidence_ids=history_ids,
                   source_before_sha256=digest(source), source_after_sha256=digest(src),
                   history_before_sha256=digest(history), history_after_sha256=digest(hist),
                   round_trip_exact=True, source_prefix_exact=True,
                   protected_content_unchanged=True,
                   source_protected_content_sha256=digest(protected_content(source)),
                   history_protected_content_sha256=digest(protected_content(history)),
                   reference_fields=sorted(REFERENCE_FIELDS), protected_fields=sorted(PROTECTED_FIELDS))
    return src, hist, mapping


def strip_exact_type(content):
    """Permit only the exact extra top-level type=json_object field."""
    try:
        obj = json.loads(content, object_pairs_hook=original._unique_object)
    except (ValueError, TypeError):
        return content, False
    if isinstance(obj, dict) and obj.get('type') == 'json_object':
        del obj['type']
        return canonical(obj), True
    return content, False


def parse_judgment(content, finish_reason, aliases, known_evidence):
    normalized, _ = strip_exact_type(content)
    return original.parse_judgment(normalized, finish_reason, aliases, known_evidence)


def request(system, payload, stage):
    result = dict(system=system, prompt=canonical(payload), thinking='enabled',
                  reasoning_effort='low', max_tokens=65536, kind=VERSION + '.' + stage,
                  manual_labels_included=False, later_research_outcomes_included=False)
    result['id'] = result['query_sha256'] = digest(result)
    return result


def dispatch_once(req, directory):
    write(directory / 'request.json', req)
    target = directory / 'completion'
    if not target.exists():
        provider.dispatch(req, target, root=ROOT)
    manifest = read(target / 'manifest.json')
    if manifest['status'] in {'prepared', 'dispatching'}:
        raise RuntimeError('unresolved_prior_dispatch:' + str(directory))
    raw = (target / 'completion.txt').read_text() if (target / 'completion.txt').exists() else ''
    normalized, changed = strip_exact_type(raw)
    record = dict(rule='remove_exact_top_level_type_json_object_only', applied=changed,
                  raw_completion_sha256=digest(raw), normalized_completion_sha256=digest(normalized),
                  provider_manifest=receipt(target / 'manifest.json'),
                  response_body=receipt(target / 'response.body') if (target / 'response.body').exists() else None)
    write(directory / 'io_normalization.json', record)
    write(directory / 'io_normalization_seal.json', receipt(directory / 'io_normalization.json'))
    return normalized, manifest


def prepare(output=DEFAULT_OUTPUT, original_root=DEFAULT_ORIGINAL):
    output, original_root = Path(output).resolve(), Path(original_root).resolve()
    if (output / 'prepared.json').exists():
        return load_protocol(output)
    old = original.load_protocol(original_root)
    if old['arms'] != ARMS or old['repeats'] != REPEATS:
        raise ValueError('original_cohort_policy_changed')
    output.mkdir(parents=True, exist_ok=True)
    cases = []
    for case in old['cases']:
        batches = []
        for before in case['batches']:
            src, hist, mapping = shorten_batch(read(before['source_payload']['path']),
                                               read(before['history_payload']['path']), before['candidates'])
            where = output / 'extraction' / case['case'] / before['batch_id']
            write(where / 'source_payload.json', src)
            write(where / 'history_payload.json', hist)
            write(where / 'identifier_map.json', mapping)
            batches.append(dict(batch_id=before['batch_id'], candidates=src['seeds'],
                source_payload=receipt(where / 'source_payload.json'), history_payload=receipt(where / 'history_payload.json'),
                identifier_map=receipt(where / 'identifier_map.json'),
                original_source_payload=before['source_payload'], original_history_payload=before['history_payload'],
                source_bytes=len(canonical(src).encode()), history_bytes=len(canonical(hist).encode())))
        cases.append({**case, 'batches': batches})
    inherited = {x['path']: x for x in old['algorithm']}
    for path in (Path(__file__), Path(provider.__file__)):
        inherited[str(path.resolve())] = receipt(path)
    protocol = {**old, 'version': VERSION, 'cases': cases,
        'original_protocol': receipt(original_root / 'prepared.json'),
        'original_seal': receipt(original_root / 'seal.json'),
        'algorithm': list(inherited.values()), 'model': provider.MODEL,
        'max_output_tokens': 65536, 'timeout_seconds': 600, 'max_response_bytes': provider.MAX_RESPONSE_BYTES,
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'frozen_before_new_provider_dispatch',
        'round_reason': 'Uniform I/O repair after initial formatting, long-ID citation and 16K response-limit failures. Not selected by gap judgment or native result.',
        'cohort_replay': 'All original batches, both arms and all three repeats, including any original success. No original completion/outcome is loaded.',
        'semantic_systems_unchanged': True,
        'judgment_system_sha256': digest(JUDGMENT_SYSTEM), 'generation_system_sha256': digest(GENERATION_SYSTEM),
        'identifier_transport': 'S001.. for original seed order; E0001.. for explicit source evidence IDs then history-only IDs. Exact references change together. Program text and base_test_id stay fixed. Round-trip proof required.',
        'output_normalization': 'Only remove an exact extra top-level type=json_object. Original strict judgment and generation schemas remain; no fuzzy repair.',
        'provider_retry_policy': 'One attempt per directory; never silently retry an incomplete or failed call.',
        'model_alias_note': 'Canonical deepseek-flash. Preserve actual response_model on every call.',
        'corrections': 'Identifier transport, 64K output channel and exact top-level type wrapper only. Original executor normalizations remain unchanged.'}
    write(output / 'prepared.json', protocol)
    write(output / 'seal.json', receipt(output / 'prepared.json'))
    return dict(cases=len(cases), batches=sum(len(c['batches']) for c in cases), judgments=protocol['judgments'])


def load_protocol(root):
    root = Path(root)
    verify(read(root / 'seal.json'))
    protocol = read(root / 'prepared.json')
    verify(protocol['original_protocol']); verify(protocol['original_seal'])
    old = original.load_protocol(Path(protocol['original_protocol']['path']).parent)
    if (protocol['version'] != VERSION or protocol['model'] != provider.MODEL
            or protocol['max_output_tokens'] != 65536 or protocol['arms'] != ARMS
            or protocol['repeats'] != REPEATS):
        raise ValueError('io_repair_policy_changed')
    for item in protocol['algorithm']:
        verify(item)
    if protocol['judgment_system_sha256'] != digest(original.JUDGMENT_SYSTEM) or protocol['generation_system_sha256'] != digest(original.GENERATION_SYSTEM):
        raise ValueError('semantic_system_changed')
    if [c['case'] for c in protocol['cases']] != [c['case'] for c in old['cases']]:
        raise ValueError('inherited_case_order_changed')
    for case, previous in zip(protocol['cases'], old['cases']):
        if {k: v for k, v in case.items() if k != 'batches'} != {k: v for k, v in previous.items() if k != 'batches'}:
            raise ValueError('inherited_case_metadata_changed')
        if len(case['batches']) != len(previous['batches']):
            raise ValueError('inherited_batch_count_changed')
        for batch, before in zip(case['batches'], previous['batches']):
            for key in ('source_payload', 'history_payload', 'identifier_map', 'original_source_payload', 'original_history_payload'):
                verify(batch[key])
            if batch['batch_id'] != before['batch_id'] or batch['original_source_payload'] != before['source_payload'] or batch['original_history_payload'] != before['history_payload']:
                raise ValueError('inherited_batch_identity_changed')
            src, hist, mapping = shorten_batch(read(before['source_payload']['path']), read(before['history_payload']['path']), before['candidates'])
            if (read(batch['source_payload']['path']) != src or read(batch['history_payload']['path']) != hist
                    or read(batch['identifier_map']['path']) != mapping or batch['candidates'] != src['seeds']):
                raise ValueError('short_identifier_projection_changed')
    return protocol


def _private(function, overrides):
    namespace = dict(function.__globals__)
    namespace.update(overrides)
    return FunctionType(function.__code__, namespace, function.__name__, function.__defaults__, function.__closure__)


def work_item(root, case, batch, arm, repeat):
    return _private(original.work_item, dict(request=request, dispatch_once=dispatch_once,
                    parse_judgment=parse_judgment))(root, case, batch, arm, repeat)


def run(root, workers=3):
    return _private(original.run, dict(load_protocol=load_protocol, work_item=work_item))(Path(root), workers, None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--original', type=Path, default=DEFAULT_ORIGINAL)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    print(canonical(prepare(args.output, args.original) if args.stage == 'prepare' else run(args.output, args.workers)))
