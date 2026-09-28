"""Bounded closure of a source producer with a typed scalar neighbour.

Only two pre-atomic program witnesses may compose. The source producer's setup
and selected q are retained; one derived argument is wrapped once in +/- 1.
This establishes a construction, not the unknown comparison boundary, runtime
type correctness, oracle applicability or an observed coverage gap.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
import copy
from dataclasses import asdict, dataclass
import json

from anchor_retrieval.syntax import Source
from generic_composition.engine import stable_id
from .frontend import is_operation_argument


@dataclass(frozen=True)
class CompositionBudget:
    max_candidates: int = 128
    max_attempts: int = 2048

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError('composition budgets must be positive integers')


class Unsupported(ValueError):
    pass


def _position(span):
    return span['path'], span['start_byte'], span['end_byte']


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


def _inside(inner, outer):
    return (inner['path'] == outer['path'] and outer['start_byte'] <= inner['start_byte']
            <= inner['end_byte'] <= outer['end_byte'])


def _parent(corpus, row, allowed_roles):
    if row.get('atomic_observation') or row.get('observation_id'):
        raise Unsupported('composition_requires_pre_atomic_parent')
    if row.get('semantic_completion') or row.get('semantic_admission'):
        raise Unsupported('composition_requires_program_parent')
    test = corpus['tests'].get(row.get('base_test_id'))
    if test is None:
        raise Unsupported('composition_base_test_missing')
    path = test['span']['path']
    metadata = corpus['sources'][path]
    if metadata.get('parse_error') or not metadata.get('complete_file', True):
        raise Unsupported('composition_source_incomplete')
    raw = metadata['code'].encode()
    for edit in row.get('edits', ()):
        if edit.get('role') not in allowed_roles:
            raise Unsupported('composition_oracle_neutralization_or_other_edit')
        span = edit['span']
        if not _inside(span, test['span']) or raw[span['start_byte']:span['end_byte']].decode() != edit['before']:
            raise Unsupported('composition_parent_edit_not_source_owned')
    return test


def _producer(corpus, frontend, row, calls, observations):
    test = _parent(corpus, row, {'source_producer_context', 'source_produced_argument'})
    arguments = [edit for edit in row.get('edits', ()) if edit.get('role') == 'source_produced_argument']
    prefixes = [edit for edit in row.get('edits', ()) if edit.get('role') == 'source_producer_context']
    if len(arguments) != 1 or not prefixes:
        raise Unsupported('composition_producer_argument_or_prefix_missing')
    argument = arguments[0]
    if _position(argument['span']) != _position(row['provenance']['recipient_argument_span']):
        raise Unsupported('composition_producer_argument_metadata_mismatch')
    if (not argument['after'].isidentifier()
            or argument['after'] not in row['provenance'].get('local_binding_renames', {}).values()):
        raise Unsupported('composition_produced_value_not_hygienic_local')
    for prefix in prefixes:
        if prefix['span']['start_byte'] != prefix['span']['end_byte'] or prefix['span']['end_byte'] > argument['span']['start_byte']:
            raise Unsupported('composition_producer_prefix_not_prior_insertion')
    q = row.get('source_observation_id')
    if (q not in observations or observations[q]['test_id'] != test['id']
            or row.get('target_capsule_id') != q or row.get('oracle', {}).get('assertion_ids') != [q]):
        raise Unsupported('composition_producer_selected_q_missing')
    call = calls.get(row.get('relation', {}).get('recipient_call_id'))
    slot = row.get('relation', {}).get('argument_slot')
    if call is None or call['test_id'] != test['id'] or not is_operation_argument(call, slot):
        raise Unsupported('composition_producer_operation_call_missing')
    actuals = [actual for actual in call.get('arguments', ()) if actual['slot'] == slot
               and _position(actual['span']) == _position(argument['span'])]
    if len(actuals) != 1:
        raise Unsupported('composition_producer_actual_span_mismatch')
    for observation in observations.values():
        if observation['test_id'] == test['id'] and observation.get('expected'):
            if _inside(argument['span'], observation['expected']['span']):
                raise Unsupported('composition_argument_is_expected_expression')
    return argument, call, q


def _scalar(corpus, row):
    _parent(corpus, row, {None, 'source_scalar_constraint'})
    relation = row.get('relation', {})
    if relation.get('construction') != 'unknown_boundary_neighbor':
        raise Unsupported('composition_scalar_not_unknown_neighbor')
    if relation.get('numeric_type', {}).get('kind') != 'integer':
        raise Unsupported('composition_source_formal_integer_evidence_missing')
    offset = relation.get('cell', {}).get('offset')
    if type(offset) is not int or offset not in {-1, 1}:
        raise Unsupported('composition_offset_not_unit_neighbor')
    if len(row.get('edits', ())) != 1 or row.get('imports'):
        raise Unsupported('composition_scalar_has_additional_edits_or_imports')
    edit = row['edits'][0]
    if edit['span']['start_byte'] == edit['span']['end_byte']:
        raise Unsupported('composition_scalar_not_argument_replacement')
    if not relation.get('comparison_span') or not relation.get('function_id'):
        raise Unsupported('composition_scalar_source_constraint_missing')
    _position(relation['call_span'])
    if type(relation.get('argument_slot')) is not int:
        raise Unsupported('composition_scalar_actual_slot_missing')
    return edit, offset


def compose_witnesses(corpus, frontend, candidates, *, budget: CompositionBudget | None = None):
    """Return additional witnesses; leave both input parents unchanged.

    Run before atomic-observation selection. Only ``source_producer_context``
    and ``scalar_source_constraint`` parents are read; arbitrary edit merging
    and recursive composition are deliberately outside this bounded relation.
    """
    budget = budget or CompositionBudget()
    skipped, outputs, attempts, seen = Counter(), [], 0, set()
    calls = {row['id']: row for row in frontend.get('calls', ())}
    observations = {row['id']: row for row in corpus.get('capsules', ())}
    scalars = defaultdict(list)
    producers = []
    def derivations():
        for row in candidates:
            if row.get('kind') != 'scalar_source_constraint' or not row.get('source_constraint_derivations'):
                yield row
                continue
            for relation in row['source_constraint_derivations']:
                # Keep the concrete parent's identity, but retain the precise
                # source derivation that licenses this composition.
                yield dict(row, relation=relation)

    for row in derivations():
        try:
            if row.get('kind') == 'scalar_source_constraint':
                edit, offset = _scalar(corpus, row)
                scalars[row['base_test_id'], _position(edit['span'])].append((row, edit, offset))
            elif row.get('kind') == 'source_producer_context':
                argument, call, q = _producer(corpus, frontend, row, calls, observations)
                producers.append((row, argument, call, q))
        except (Unsupported, KeyError, TypeError, UnicodeDecodeError) as error:
            skipped[str(error) if isinstance(error, Unsupported) else 'composition_parent_metadata_invalid'] += 1

    def rank(row):
        return corpus['tests'][row['base_test_id']].get('retrieval_rank') or 10**9, row['base_test_id'], row['id']

    parents = defaultdict(list)
    def pairs(producer, matches):
        for scalar in sorted(matches, key=lambda item: item[0]['id']):
            yield producer, scalar

    for producer in sorted(producers, key=lambda item: rank(item[0])):
        row, argument, _, _ = producer
        matches = scalars.get((row['base_test_id'], _position(argument['span'])), [])
        if not matches:
            skipped['composition_no_same_base_actual_scalar'] += 1
            continue
        parents[row['base_test_id']].append(pairs(producer, matches))

    def result(exhausted=False):
        return {'domain': 'source_witness_composition', 'candidates': outputs, 'attempts': attempts,
                'skipped': dict(sorted(skipped.items())), 'budget': asdict(budget), 'budget_exhausted': exhausted}

    if corpus['language'] not in {'python', 'go'}:
        skipped['composition_language_unsupported'] += 1
        return result()
    tests = sorted(parents, key=lambda key: (corpus['tests'][key].get('retrieval_rank') or 10**9, key))
    for producer, scalar in _round_robin(_round_robin(parents[key]) for key in tests):
        if attempts >= budget.max_attempts:
            skipped['composition_attempt_budget'] += 1
            return result(True)
        attempts += 1
        row, argument, call, q = producer
        scalar_row, scalar_edit, offset = scalar
        if (argument['before'] != scalar_edit['before'] or row['language'] != scalar_row['language']
                or _position(call['span']) != _position(scalar_row['relation']['call_span'])
                or row['relation']['argument_slot'] != scalar_row['relation']['argument_slot']):
            skipped['composition_actual_call_or_slot_mismatch'] += 1
            continue
        composed = copy.deepcopy(row)
        updated = next(edit for edit in composed['edits'] if edit.get('role') == 'source_produced_argument')
        updated['after'] = '(' + argument['after'] + ') ' + ('+ ' if offset > 0 else '- ') + '1'
        signature = json.dumps([row['base_test_id'], q, composed['edits']], sort_keys=True, ensure_ascii=True)
        if signature in seen:
            skipped['composition_duplicate'] += 1
            continue
        path = argument['span']['path']
        source = corpus['sources'][path]
        raw = source['code'].encode()
        for edit in sorted(composed['edits'], key=lambda edit: (edit['span']['start_byte'], edit['span']['end_byte']), reverse=True):
            raw = raw[:edit['span']['start_byte']] + edit['after'].encode() + raw[edit['span']['end_byte']:]
        try:
            text = raw.decode()
            if Source(path, text, row['language']).root.has_error:
                raise ValueError('syntax')
            if row['language'] == 'python':
                ast.parse(text)
        except (ValueError, SyntaxError):
            skipped['composition_parse_error'] += 1
            continue
        seen.add(signature)
        parent_ids = [row['id'], scalar_row['id']]
        composed['id'] = stable_id('witness_composition', *parent_ids, updated['after'], q)
        composed['kind'] = 'source_witness_composition'
        composed['parent_candidate_ids'] = parent_ids
        composed['source_test_ids'] = sorted(set(row.get('source_test_ids', ())) | set(scalar_row.get('source_test_ids', ())))
        composed['relation'] = {'domain': 'source_witness_composition', 'construction': 'producer_then_typed_unknown_unit_neighbor',
                                'status': 'hypothesis_runtime_relation_unconfirmed', 'parent_candidate_ids': parent_ids,
                                'argument_span': copy.deepcopy(argument['span']), 'offset': offset,
                                'numeric_type': copy.deepcopy(scalar_row['relation']['numeric_type']),
                                'producer_relation': copy.deepcopy(row['relation']),
                                'scalar_relation': copy.deepcopy(scalar_row['relation']),
                                'evaluation': 'original_producer_prefix_retained_derived_argument_evaluated_once',
                                'applicability': 'unknown_requires_independent_admission'}
        composed['provenance']['composition'] = {'parent_candidate_ids': parent_ids, 'argument_span': copy.deepcopy(argument['span']),
                                                'producer_argument_after': argument['after'], 'offset': offset,
                                                'scalar_source_spans': copy.deepcopy(scalar_row.get('provenance', {}).get('source_spans', [])),
                                                'retained_observation_id': q, 'oracle_edits': False, 'neutralizations': False}
        composed['provenance']['composition']['scalar_derivation'] = copy.deepcopy(scalar_row['relation'])
        composed['provenance']['composition']['scalar_source_spans'].append(copy.deepcopy(scalar_row['relation']['comparison_span']))
        composed['provenance']['source_spans'].extend(copy.deepcopy(scalar_row.get('provenance', {}).get('source_spans', [])))
        composed['selection']['composition_schedule'] = 'base_test_then_producer_parent_round_robin'
        outputs.append(composed)
        if len(outputs) >= budget.max_candidates:
            skipped['composition_candidate_budget'] += 1
            return result(True)
    return result()
