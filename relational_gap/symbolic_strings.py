"""Source string-context edits that preserve Python interpolation expressions.

The finite grammar changes one outer static JoinedStr segment using an edit
learned at the same call port. FormattedValue nodes, their order, conversions,
and nested format specifications survive an AST round trip unchanged. No
parameter rows, interpolation expressions, or subject code are evaluated.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
import copy
from dataclasses import asdict, dataclass
import difflib

from anchor_retrieval.syntax import Source
from prototypes.local_literal_contexts import learn
from generic_composition.corpus import source_text
from generic_composition.edits import learn_literal_edits, tokens
from generic_composition.engine import expected_only, slot_key, stable_id


@dataclass(frozen=True)
class SymbolicStringBudget:
    max_candidates: int = 128
    max_attempts: int = 8000
    max_rules_per_slot: int = 64
    max_donors_per_slot: int = 48
    neighbors: int = 4
    max_tokens: int = 256
    max_expression_bytes: int = 4096
    max_segments: int = 16


def _position(row):
    value = row.get('span', row)
    return value['path'], value['start_byte'], value['end_byte']


def _round_robin(streams):
    queue = deque(iter(stream) for stream in streams)
    while queue:
        stream = queue.popleft()
        item = next(stream, None)
        if item is not None:
            queue.append(stream)
            yield item


def _parse(donor, budget, skipped):
    text = donor.get('text', '')
    if len(text.encode()) > budget.max_expression_bytes:
        skipped['expression_size_budget'] += 1
        return None
    try:
        tree = ast.parse(text, mode='eval').body
    except (SyntaxError, ValueError, RecursionError):
        return None
    if isinstance(tree, ast.Constant) and type(tree.value) is str:
        parts = [(0, tree.value)]
        holes = []
    elif isinstance(tree, ast.JoinedStr):
        parts = [(index, item.value) for index, item in enumerate(tree.values)
                 if isinstance(item, ast.Constant) and type(item.value) is str]
        holes = [item for item in tree.values if isinstance(item, ast.FormattedValue)]
        if len(parts) > budget.max_segments:
            skipped['static_segment_budget'] += 1
            return None
    else:
        return None
    if any(len(tokens(value)) > budget.max_tokens for _, value in parts):
        skipped['static_token_budget'] += 1
        return None
    return {'donor': donor, 'tree': tree, 'parts': parts, 'holes': holes}


def _fragments(template):
    # Two symbolic donors align static segments by their surrounding hole
    # positions. Whole closed strings form their own source-pair family.
    family = ('symbolic', len(template['holes'])) if template['holes'] else ('closed',)
    for index, value in template['parts']:
        if value:
            preceding = (sum(isinstance(item, ast.FormattedValue) for item in template['tree'].values[:index])
                         if template['holes'] else 0)
            yield {'template': template, 'index': index, 'value': value,
                   'family': (*family, preceding) if template['holes'] else family}


def _learn_rules(members, rank, budget):
    families = defaultdict(list)
    for template in sorted(members, key=lambda t: (rank[t['donor']['test_id']], _position(t['donor']))):
        for fragment in _fragments(template):
            families[fragment['family']].append(fragment)
    streams = []
    for family in sorted(families, key=repr):
        unique = {}
        for fragment in families[family]:
            unique.setdefault(fragment['value'], fragment)
        values = list(unique.values())[:budget.max_donors_per_slot]
        learned = {}
        for before in values:
            nearest = sorted((after for after in values if after['value'] != before['value']), key=lambda after: (
                -difflib.SequenceMatcher(a=tokens(before['value']), b=tokens(after['value']), autojunk=False).ratio(),
                _position(after['template']['donor']), after['index']))[:budget.neighbors]
            for after in nearest:
                rules = [('unique_local_token_anchor', edit) for edit in learn(
                    before['value'], after['value'], max_tokens=budget.max_tokens)]
                rules += [('whole_static_segment_pattern', edit) for edit in learn_literal_edits(
                    before['value'], after['value'], max_tokens=budget.max_tokens) if edit.mode == 'literal']
                for scope, edit in rules:
                    learned.setdefault((scope, edit.fingerprint), (scope, edit, before, after))
        streams.append(sorted(learned.values(), key=lambda row: (
            len(row[1].pattern) if row[0] == 'unique_local_token_anchor' else len(row[1].before),
            row[0], row[1].fingerprint)))
    rules, seen = [], set()
    for rule in _round_robin(streams):
        key = rule[0], rule[1].fingerprint
        if key in seen:
            continue
        seen.add(key)
        rules.append(rule)
        if len(rules) >= budget.max_rules_per_slot:
            break
    return rules


def _apply(template, rule, skipped):
    scope, edit, *_ = rule
    matches = []
    for index, value in template['parts']:
        if scope == 'unique_local_token_anchor':
            matches.extend((index, at) for at in edit.positions(value))
        elif edit.apply(value) is not None:
            matches.append((index, 0))
    if len(matches) != 1:
        if matches:
            skipped['static_context_ambiguous'] += 1
        return None
    index, anchor = matches[0]
    old = template['tree'].values[index].value
    value = edit.apply(old)
    if value is None:
        return None
    changed = copy.deepcopy(template['tree'])
    changed.values[index].value = value
    try:
        text = ast.unparse(changed)
        restored = ast.parse(text, mode='eval').body
    except (SyntaxError, ValueError, RecursionError):
        skipped['symbolic_render_parse_error'] += 1
        return None
    before = [ast.dump(hole, include_attributes=False) for hole in template['holes']]
    after = ([ast.dump(item, include_attributes=False) for item in restored.values
              if isinstance(item, ast.FormattedValue)] if isinstance(restored, ast.JoinedStr) else [])
    if before != after or ast.dump(changed, include_attributes=False) != ast.dump(restored, include_attributes=False):
        skipped['interpolation_ast_roundtrip_mismatch'] += 1
        return None
    return {'text': text, 'index': index, 'anchor': anchor, 'before': old, 'after': value,
            'interpolation_count': sum(isinstance(item, ast.FormattedValue) for item in ast.walk(restored))}


def _fragment_provenance(fragment):
    donor = fragment['template']['donor']
    return {'test_id': donor['test_id'], 'source_expression_span': donor['span'],
            'source_expression': donor['text'], 'outer_static_segment_index': fragment['index'],
            'static_value': fragment['value'], 'source_family': list(fragment['family'])}


def generate_symbolic_strings(corpus, *, budget: SymbolicStringBudget | None = None):
    """Return source-owned hypotheses with the original parameterized q frame."""
    budget = budget or SymbolicStringBudget()
    if any(type(value) is not int or value < 1 for value in asdict(budget).values()):
        raise ValueError('Symbolic string budgets must be positive integers')
    skipped, candidates, attempts, seen = Counter(), [], 0, set()

    def result(exhausted=False):
        return {'candidates': candidates, 'skipped': dict(sorted(skipped.items())),
                'attempts': attempts, 'budget_exhausted': exhausted,
                'budget': asdict(budget), 'domain': 'symbolic_string_context'}

    if corpus['language'] != 'python':
        skipped['joined_string_language_not_supported'] += 1
        return result()
    # Import lazily so transforms can later compose this standalone domain.
    from .transforms import _root_ports

    tests = corpus['tests']
    ordered = sorted(tests, key=lambda key: (tests[key].get('retrieval_rank') or 10**9,
                                            _position(tests[key]), key))
    rank = {test_id: index for index, test_id in enumerate(ordered)}
    capsules = defaultdict(list)
    for capsule in corpus.get('capsules', ()):
        capsules[capsule['test_id']].append(capsule)
    sources = {path: Source(path, metadata['code'], corpus['language'])
               for path, metadata in corpus['sources'].items()
               if metadata.get('complete_file', True) and not metadata.get('parse_error')}
    groups, source_seen = defaultdict(list), set()
    for donor in corpus.get('donors', ()):
        if (donor['test_id'] not in tests or not capsules[donor['test_id']]
                or donor.get('role') == 'expected' or expected_only(donor)
                or donor['span']['path'] not in sources):
            continue
        if source_text(corpus, donor['span']) != donor.get('text'):
            skipped['non_source_expanded_expression'] += 1
            continue
        ports = _root_ports(sources[donor['span']['path']], donor)
        if not ports:
            continue
        template = _parse(donor, budget, skipped)
        if template is None:
            continue
        for port in ports:
            slot = slot_key(port)
            key = slot, donor['test_id'], _position(donor)
            if key not in source_seen:
                source_seen.add(key)
                groups[slot].append(template)

    plans = defaultdict(list)
    for slot, members in sorted(groups.items(), key=lambda pair: (
            min(rank[t['donor']['test_id']] for t in pair[1]), repr(pair[0]))):
        targets = [template for template in members if template['holes']]
        if not targets:
            continue
        rules = _learn_rules(members, rank, budget)
        for target in sorted(targets, key=lambda t: (rank[t['donor']['test_id']], _position(t['donor']))):
            plans[target['donor']['test_id']].append((slot, target, rules))

    def target_stream(slot, target, rules):
        for rule in rules:
            yield slot, target, rule

    streams = [_round_robin(target_stream(*plan) for plan in plans[test_id])
               for test_id in ordered if test_id in plans]
    for slot, target, rule in _round_robin(streams):
        if attempts >= budget.max_attempts:
            skipped['attempt_budget'] += 1
            return result(True)
        attempts += 1
        applied = _apply(target, rule, skipped)
        if applied is None:
            continue
        donor = target['donor']
        edits = [{'span': donor['span'], 'before': donor['text'], 'after': applied['text']}]
        identifier = stable_id('symbolic_string_context', donor['test_id'], edits)
        if identifier in seen:
            continue
        seen.add(identifier)
        scope, edit, before, after = rule
        origins = [before['template']['donor'], after['template']['donor']]
        candidates.append({
            'id': identifier, 'base_test_id': donor['test_id'],
            'source_test_ids': sorted({origin['test_id'] for origin in origins}),
            'language': 'python', 'kind': 'symbolic_string_context', 'imports': [], 'edits': edits,
            'relation': {'domain': 'symbolic_string_context', 'slot': list(slot),
                         'cell': 'source_fragment_with_original_interpolation',
                         'status': 'statically_constructed_runtime_unconfirmed',
                         'anchoring': scope, 'target_match_count': 1,
                         'target_static_segment_index': applied['index'],
                         'target_token_anchor': applied['anchor'],
                         'static_before': applied['before'], 'static_after': applied['after'],
                         'edit': edit.as_dict(),
                         'interpolation_count': applied['interpolation_count'],
                         'interpolation_precision': 'formatted_value_ast_and_order_preserved',
                         'parameter_frame': 'original_test_parameters_and_rows_retained',
                         'semantic_status': 'source_context_hypothesis; grammar_and_oracle_unknown'},
            'oracle': {'mode': 'retain_all', 'source_test_id': donor['test_id'],
                       'assertion_ids': [q['id'] for q in capsules[donor['test_id']]],
                       'applicability': 'requires_independent_admission', 'basis': None},
            'provenance': {'target_span': donor['span'],
                           'source_spans': [origin['span'] for origin in origins],
                           'source_donor_ids': [origin['id'] for origin in origins],
                           'source_fragments': [_fragment_provenance(before), _fragment_provenance(after)],
                           'binding_precision': 'no_interpolation_or_free_identifier_changes',
                           'unknowns': ['source_presence_is_not_execution', 'grammar_contract', 'oracle_transport']},
            'selection': {'base_retrieval_rank': tests[donor['test_id']].get('retrieval_rank'),
                          'schedule': 'parent_then_target_expression_round_robin'},
        })
        if len(candidates) >= budget.max_candidates:
            skipped['candidate_budget'] += 1
            return result(True)
    return result()
