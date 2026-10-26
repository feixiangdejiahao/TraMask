"""Source-only opportunity census, not a combination generator or validity check.

Find an exact producer-call result used as another call's argument, linked by
the frozen frontend to a test observation. Match the producer's returned MAY
field reads to uniquely resolved writer calls in source tests. No transport,
alias, execution, oracle, or new-dependency conclusion follows from a match.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(ROOT))

from anchor_retrieval.syntax import Source, child, units, walk
from prototypes.observation_address_effects import CONTROLS, SCOPES, summarize_method


def pos(ref):
    return ref['path'], ref['start_byte'], ref['end_byte']


def frozen(receipt):
    raw = Path(receipt['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != receipt['sha256']:
        raise ValueError('Changed source input: ' + receipt['path'])
    return json.loads(raw)


def resolved(call):
    targets = call.get('targets', [])
    return targets[0]['function_id'] if len(targets) == 1 and targets[0].get('resolved') else None


def make_index(frontend):
    sources = {p: Source(p, row['code'], row.get('language', 'python'))
               for p, row in frontend['sources'].items()
               if row.get('complete_file', True) and not row.get('parse_error')}
    found = {}
    packages = {}
    for source in sources.values():
        found.update((u.id, u) for u in units(source)[0])
        if source.language == 'go':
            packages[source.path] = next((source.text(n.named_children[0])
                for n in source.root.named_children if n.type == 'package_clause' and n.named_children), '')
    return SimpleNamespace(sources=sources, units=found, go_packages=packages)


def statement(unit, location):
    body = unit.body
    container = next((n for n in body.named_children if n.type == 'statement_list'), body)
    return next((n for n in container.named_children if n.start_byte <= location['start_byte']
                 and location['end_byte'] <= n.end_byte), None)


def continuity(unit, binding, consumer, argument, bindings):
    """Classify a direct root-local value edge; uncertain paths remain explicit."""
    reasons = []
    if binding.get('contexts') or consumer.get('contexts'):
        reasons.append('binding_or_use_has_control_context')
    if not binding.get('simple_name') or not binding.get('projection_known'):
        reasons.append('binding_not_exact_single_local')
    name = binding['name']
    if name in unit.params:
        reasons.append('binding_is_parameter_reassignment')
    start, stop = binding['definition_end'], argument['span']['start_byte']
    if start > stop:
        reasons.append('definition_not_before_use')
    if any(b['id'] != binding['id'] and b['name'] == name and
           start <= b['span']['start_byte'] < stop for b in bindings):
        reasons.append('intervening_redefinition')
    definition_statement = statement(unit, binding['span'])
    use_statement = statement(unit, consumer['span'])
    if definition_statement is None or use_statement is None:
        reasons.append('root_statement_unavailable')
    for node in walk(unit.body):
        if node == unit.body:
            continue
        if node.type in SCOPES:
            reasons.append('nested_scope_capture_not_analyzed')
            break
        if node.type in {'global_statement', 'nonlocal_statement'}:
            reasons.append('root_has_external_binding_directive')
        if (node.type in CONTROLS and node.start_byte < stop
                and start <= node.end_byte):
            reasons.append('control_between_definition_and_use')
        if node.type in {'await', 'await_expression', 'yield', 'yield_expression', 'go_statement', 'defer_statement'}:
            if node.start_byte < stop and start <= node.end_byte:
                reasons.append('deferred_or_async_evaluation')
        if unit.source.language == 'go' and node.type == 'unary_expression':
            if unit.source.text(child(node, 'operator')) == '&' and unit.source.text(child(node, 'operand')) == name:
                reasons.append('local_address_taken')
    if unit.source.language in {'go', 'typescript'}:
        declarations = {'short_var_declaration', 'var_spec', 'variable_declarator'}
        declared = any(node.type in declarations and
            any(unit.source.text(n) == name and n.type == 'identifier'
                for n in walk(child(node, 'left', 'name') or node))
            and node.start_byte <= binding['span']['start_byte'] for node in walk(unit.body))
        if not declared:
            reasons.append('root_local_declaration_not_established')
    return sorted(set(reasons))


def analyze(frontend):
    started = time.monotonic()
    index = make_index(frontend)
    calls = frontend['calls']
    by_call = {pos(c['span']): c for c in calls}
    by_binding = {b['id']: b for b in frontend['bindings']}
    bindings_by_test = defaultdict(list)
    for binding in frontend['bindings']:
        bindings_by_test[binding['test_id']].append(binding)
    summaries = {uid: summarize_method(index, uid)
                 for uid in sorted({resolved(c) for c in calls} - {None})}
    writer_map = defaultdict(list)
    for call in calls:
        summary = summaries.get(resolved(call), {})
        for effect in summary.get('writes', []):
            writer_map[tuple(effect['owner_key']), effect['field']].append(dict(
                call_id=call['id'], test_id=call['test_id'], call=call['span'],
                callee=call['callee'], function_id=resolved(call), effect=effect,
                contexts=call.get('contexts', []),
                transportability='not_analyzed', object_identity='not_compared'))
    observations = {q['id']: q for q in frontend.get('observations', [])}
    rows = []
    skips = Counter()
    for consumer in calls:
        for argument in consumer.get('arguments', []):
            if argument.get('spread'):
                skips['spread_argument'] += 1
                continue
            producer = by_call.get(pos(argument['span']))
            binding = None
            kind = 'inline_exact_call'
            if producer is None and argument.get('kind') == 'identifier':
                binding_id = (argument.get('binding') or {}).get('binding_id')
                binding = by_binding.get(binding_id)
                if binding is not None and binding.get('value'):
                    producer = by_call.get(pos(binding['value']['span']))
                    kind = 'exact_local_definition'
            if producer is None or producer['id'] == consumer['id'] or producer['test_id'] != consumer['test_id']:
                continue
            uid = resolved(producer)
            if uid is None:
                skips['producer_resolution_not_unique'] += 1
                continue
            summary = summaries.get(uid, {})
            if not summary.get('reads'):
                skips['producer_no_supported_return_read'] += 1
                continue
            qids = consumer.get('observation_ids', [])
            if not qids:
                skips['consumer_has_no_frontend_observation_link'] += 1
                continue
            unit = index.units.get(consumer['test_id'])
            uncertain = []
            if unit is None:
                uncertain.append('test_unit_unavailable')
            elif binding is not None:
                uncertain += continuity(unit, binding, consumer, argument, bindings_by_test[consumer['test_id']])
            if producer.get('contexts') or consumer.get('contexts'):
                uncertain.append('producer_or_consumer_context_unproved')
            for effect in summary['reads']:
                writers = [w for w in writer_map[tuple(effect['owner_key']), effect['field']]
                           if w['call_id'] != producer['id']]
                if not writers:
                    skips['read_has_no_other_resolved_test_writer'] += 1
                    continue
                path = producer['span']['path']
                source = index.sources[path]
                a = min(producer['span']['start_byte'], binding['span']['start_byte'] if binding else producer['span']['start_byte'])
                b = consumer['span']['end_byte']
                rows.append(dict(producer_call=producer['span'], producer_call_id=producer['id'],
                    producer_function_id=uid, producer_text=source.data[producer['span']['start_byte']:producer['span']['end_byte']].decode(),
                    read_effect=effect, consumer_call=consumer['span'], consumer_call_id=consumer['id'],
                    consumer_callee=consumer['callee'], consumer_role=consumer.get('role'),
                    consumer_function_id=resolved(consumer), argument_slot=argument['slot'],
                    argument=argument['span'], binding=binding, edge_kind=kind,
                    continuity_status='context_or_binding_unknown' if uncertain else 'direct_lexical_value_edge',
                    continuity_unknowns=sorted(set(uncertain)), test_id=consumer['test_id'],
                    observation_ids=qids, observation_spans=[observations[q]['assertion_span'] for q in qids if q in observations and observations[q].get('assertion_span')],
                    q_link_status='frozen_frontend_may_observation_link_not_recomputed',
                    writer_calls=writers, writer_call_count=len(writers),
                    source_fragment=source.data[a:b].decode(),
                    source_sha256=hashlib.sha256(source.data).hexdigest(),
                    key_compatibility='not_solved', donor_transportability='not_analyzed',
                    existing_versus_missing_combination='not_classified'))
    counts = Counter()
    for row in rows:
        counts[row['continuity_status']] += 1
        counts['consumer_role:' + str(row['consumer_role'])] += 1
        counts['address:' + ('indexed' if row['read_effect']['key'] is not None else 'plain')] += 1
    return dict(paths=rows, counts=dict(counts), skips=dict(skips),
                calls_considered=len(calls), uniquely_resolved_methods=len(summaries),
                elapsed_seconds=time.monotonic()-started)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError('Refusing to overwrite census')
    raw = args.inventory.read_bytes()
    inventory = json.loads(raw)
    rows = []
    started = time.monotonic()
    for case in inventory['cases']:
        result = analyze(frozen(case['frontend']))
        rows.append(dict(case=case['case'], language=case['language'], frontend=case['frontend'], **result))
        print(json.dumps(dict(case=case['case'], paths=len(result['paths']), counts=result['counts'])), flush=True)
    modules = [Path(__file__), ROOT/'prototypes/observation_address_effects.py',
               ROOT/'anchor_retrieval/syntax.py']
    result = dict(version='mixed-value-state-source-opportunities.v1',
        inventory=dict(path=str(args.inventory.resolve()), sha256=hashlib.sha256(raw).hexdigest()),
        modules=[dict(path=str(p.resolve()), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in modules],
        rows=rows, elapsed_seconds=time.monotonic()-started, native_executions=0,
        provider_calls=0, reads_evaluation_outcomes=False,
        limitation='Source opportunity only. Exact returned-value argument edge plus MAY same-field writer does not prove transportability, aliasing, write execution, missing combination, oracle validity, or fault detection.')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
