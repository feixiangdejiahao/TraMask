"""Replay a source-template restriction over one complete reviewed native round.

No provider call or subject execution occurs. An unavailable required native
prefix withholds the trial; a later archived failure cannot fill that gap.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import negative_exception_template as predicate
from relation_search import source_control_context
from scripts import run_archived_component_chain as archive

VERSION = 'negative-exception-template-ablation.v1'


def controlled(outcome):
    native = outcome.get('native') or {}
    return (outcome.get('transport', {}).get('status') == 'matched'
            and native.get('controls', {}).get('status') == 'all_source_controls_passed'
            and native.get('controlled_failure') is True)


def replay_case(case, source_result, decisions, classifications):
    """Replay only the existing fixed prefix after a source-only restriction."""
    if source_result['case'] != case['case']:
        raise ValueError('Native trial identity differs')
    attempts = {row['rank']: row for row in source_result['attempts']}
    if len(attempts) != len(source_result['attempts']):
        raise ValueError('Duplicate native rank')
    result = dict(case=case['case'], attempts=[], alert=None,
                  stop_reason='no_eligible_supported_source_template')
    for entry in case['candidates']:
        key = (case['case'], entry['rank'])
        if classifications[key]['status'] != 'eligible' or not decisions[key]['admitted']:
            continue
        if entry['rank'] not in attempts:
            result['stop_reason'] = 'required_native_prefix_not_observed'
            break
        attempt = attempts[entry['rank']]
        if attempt['program'] != entry['program']:
            raise ValueError('Reused program differs')
        result['attempts'].append(attempt)
        native = attempt['initial'].get('native')
        if native is None:
            result['stop_reason'] = 'emission_or_transport_unavailable'
            continue
        if native.get('controls', {}).get('status') != 'all_source_controls_passed':
            result['stop_reason'] = 'source_control_unavailable_or_failed'
            break
        if controlled(attempt['initial']):
            result['stop_reason'] = 'first_failure_unconfirmed'
            if controlled(attempt.get('confirmation', {})):
                alert = dict(program=entry['program'], initial=attempt['initial_receipt'],
                    confirmation=attempt['confirmation_receipt'], semantic=decisions[key]['decision'],
                    validity='pending_independent_full_test_audit')
                if source_result['alert'] != alert:
                    raise ValueError('Replayed alert differs from the complete archived alert')
                result.update(alert=alert, stop_reason='repeated_admitted_negative_template_failure')
            break
        result['stop_reason'] = 'candidate_budget_exhausted'
    return result


def load_base(component):
    loaded, reports, sources = archive.load_components([component])
    name = component['name']
    protocol = archive.read(component['prepared']['path'])
    summary = archive.read(component['summary']['path'])
    if protocol.get('version') != 'controlled-absence-null-search.v1':
        raise ValueError('Unsupported source experiment')
    semantic = archive.read(summary['semantic_summary']['path'])
    return protocol, summary, semantic, reports[name], sources


def classifications(protocol):
    rows = []
    for case in protocol['cases']:
        corpus = archive.read(case['inputs']['corpus.json']['path'])
        for entry in case['candidates']:
            rows.append(dict(case=case['case'], rank=entry['rank'], program=entry['program'],
                classification=predicate.classify(corpus, archive.read(entry['program']['path']))))
    return rows


def prepare(args):
    component = archive.read(args.component)
    base, summary, semantic, provenance, sources = load_base(component)
    rows = classifications(base)
    algorithm = {name: archive.frozen(path) for name, path in {
        'driver': __file__, 'predicate': predicate.__file__,
        'source_bindings': source_control_context.__file__,
        'archive': archive.__file__, 'gated_native': archive.gated_native.__file__,
    }.items()}
    record = dict(version=VERSION, base_component=component,
        component_spec=archive.frozen(args.component), algorithm=algorithm,
        policy=predicate.POLICY, cases=[c['case'] for c in base['cases']],
        source_inventory=sources, classifications=rows,
        provenance=provenance, trial_denominator=base['trial_denominator'],
        retrospective=True, new_native_executions=0, new_provider_calls=0,
        evaluation_labels_used=False,
        source_pool='All fixed candidates, original ranks, no refill.',
        native_policy='Replay admitted eligible ranks in order. Stop at first controlled failure and its existing repeat. Stop without alert if a required native prefix is absent.',
        development_limitation='The source predicate was designed after the earlier round was audited. This is a development ablation, not a prospective unseen evaluation.',
        created_utc=datetime.now(timezone.utc).isoformat())
    args.output.mkdir(parents=True, exist_ok=False)
    archive.write(args.output/'prepared.json', record)
    archive.write(args.output/'seal.json', archive.frozen(args.output/'prepared.json'))
    return dict(trials=len(record['cases']), candidates=len(rows),
                eligible=sum(r['classification']['status']=='eligible' for r in rows))


def derive(base, summary, semantic, rows):
    expected = {(c['case'], e['rank']): e for c in base['cases'] for e in c['candidates']}
    selected = {(r['case'], r['rank']): r for r in rows}
    if len(selected) != len(rows) or set(selected) != set(expected):
        raise ValueError('Template classifications must cover all source candidates')
    if any(selected[key]['program'] != entry['program'] for key, entry in expected.items()):
        raise ValueError('Template candidate receipt differs')
    decisions = {(r['case'], r['rank']): r for r in semantic['results']}
    if len(decisions) != len(semantic['results']) or set(decisions) != set(expected):
        raise ValueError('Semantic decisions must cover all source candidates')
    original = archive.complete_index(summary['results'], [c['case'] for c in base['cases']])
    classifications_ = {key: row['classification'] for key, row in selected.items()}
    return [replay_case(case, original[case['case']], decisions, classifications_) for case in base['cases']]


def run(args):
    root = args.input
    protocol = archive.read(root/'prepared.json')
    if (protocol.get('version') != VERSION
            or archive.read(root/'seal.json') != archive.frozen(root/'prepared.json')):
        raise ValueError('Changed ablation protocol')
    for receipt in protocol['algorithm'].values():
        if archive.frozen(receipt['path']) != receipt:
            raise ValueError('Changed ablation implementation')
    if archive.frozen(protocol['component_spec']['path']) != protocol['component_spec']:
        raise ValueError('Changed component declaration')
    base, summary, semantic, provenance, sources = load_base(protocol['base_component'])
    if provenance != protocol['provenance'] or sources != protocol['source_inventory']:
        raise ValueError('Changed base provenance')
    if classifications(base) != protocol['classifications']:
        raise ValueError('Changed source-template classifications')
    results = derive(base, summary, semantic, protocol['classifications'])
    output = dict(version=VERSION, prepared=archive.frozen(root/'prepared.json'),
        results=results, trial_denominator=len(results),
        detector_alerts=sum(bool(r['alert']) for r in results),
        fresh_native_executions=0, fresh_provider_calls=0,
        reused_native_outcomes=sum('initial' in a for r in results for a in r['attempts'])+
            sum('confirmation' in a for r in results for a in r['attempts']),
        base_summary=protocol['base_component']['summary'],
        semantic_summary=summary['semantic_summary'],
        retrospective=True, independent_audit_complete=False)
    archive.write(root/'summary.json', output)
    archive.write(root/'summary_seal.json', archive.frozen(root/'summary.json'))
    return {key: value for key, value in output.items() if key != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--component', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    arguments = parser.parse_args()
    import json
    print(json.dumps(prepare(arguments) if arguments.stage == 'prepare' else run(arguments)))
