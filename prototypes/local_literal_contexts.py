"""Transfer a source string edit at a uniquely matched local token boundary.

The surrounding string is deliberately left untouched. This is a syntactic
context hypothesis, not a protocol grammar or a claim about expected behavior.
Rules require source witnesses and a common call port. Resolved identities are
preferred; unresolved receivers retain an explicitly approximate origin key.
"""
from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
import difflib
import re

from anchor_retrieval.syntax import CALLS, FUNCTIONS, Source, call_parts, child, walk
from generic_composition import engine
from generic_composition.edits import encode_literal, token_sort, tokens


def _pattern(sequence, changed=()):
    holes, result = {}, []
    for i, token in enumerate(sequence):
        sort = token_sort(token)
        if sort != 'literal' and i not in changed:
            result.append(('hole', sort, holes.setdefault((sort, token), len(holes))))
        else:
            result.append(('literal', token))
    return tuple(result)


def _matches(pattern, sequence):
    bound = {}
    for item, token in zip(pattern, sequence):
        if item[0] == 'literal':
            if token != item[1]:
                return False
        else:
            _, kind, identifier = item
            if token_sort(token) != kind or (identifier in bound and bound[identifier] != token):
                return False
            bound[identifier] = token
    return len(pattern) == len(sequence)


@dataclass(frozen=True)
class LocalEdit:
    pattern: tuple
    left: int
    removed: int
    inserted: tuple[str, ...]

    @property
    def fingerprint(self):
        return engine.stable_id(self.pattern, self.left, self.removed, self.inserted)

    def positions(self, value):
        seq = tokens(value)
        return [i for i in range(len(seq) - len(self.pattern) + 1)
                if _matches(self.pattern, seq[i:i + len(self.pattern)])]

    def apply(self, value):
        positions = self.positions(value)
        if len(positions) != 1:
            return None
        seq = tokens(value)
        start = positions[0] + self.left
        result = ''.join(seq[:start] + self.inserted + seq[start + self.removed:])
        return result if result != value else None

    def as_dict(self):
        return {'pattern': [list(p) for p in self.pattern], 'left': self.left,
                'removed': self.removed, 'inserted': list(self.inserted),
                'fingerprint': self.fingerprint}


def learn(before, after, *, window=4, max_tokens=256, max_change=12):
    a, b = tokens(before), tokens(after)
    if not a or not b or max(len(a), len(b)) > max_tokens:
        return []
    changes = [row for row in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes()
               if row[0] != 'equal']
    if len(changes) != 1:
        return []
    _, lo, hi, new_lo, new_hi = changes[0]
    if max(hi - lo, new_hi - new_lo) > max_change:
        return []
    result, seen = [], set()
    # Keep both orientations: a left boundary and a right boundary preserve
    # different surrounding contexts. At least one punctuation token anchors
    # the operation; a bare word/number hole must not match arbitrary fields.
    choices = sorted(((left, right) for left in range(window + 1) for right in range(window + 1)
                      if 0 < left + right and lo >= left and hi + right <= len(a)),
                     key=lambda p: (sum(p), min(p), p))
    for left, right in choices:
        sequence = a[lo - left:hi + right]
        stable = a[lo - left:lo] + a[hi:hi + right]
        if not any(token_sort(t) == 'literal' and not t.isspace() for t in stable):
            continue
        pattern = _pattern(sequence, range(left, left + hi - lo))
        edit = LocalEdit(pattern, left, hi - lo, b[new_lo:new_hi])
        if edit.fingerprint in seen or edit.apply(before) != after:
            continue
        seen.add(edit.fingerprint)
        result.append(edit)
    return result


def _port_identity(corpus, donor, port, sources):
    identity = port.get('callee_identity') or {}
    key = engine.slot_key(port)
    if identity.get('canonical'):
        return key, identity
    callee = port.get('callee', '')
    match = re.fullmatch(r'([A-Za-z_]\w*)(\.[A-Za-z_]\w*)+', callee)
    if not match:
        return key, identity
    root = callee.split('.')[0]
    test = corpus['tests'][donor['test_id']]
    path = test['span']['path']
    if path not in sources:
        sources[path] = Source(path, corpus['sources'][path]['code'], corpus['language'])
    source = sources[path]
    latest = None
    body = source.root.descendant_for_byte_range(test['body_span']['start_byte'], test['body_span']['end_byte'] - 1)
    for node in walk(body):
        if not test['body_span']['start_byte'] <= node.start_byte < node.end_byte <= port['call_span']['start_byte']:
            continue
        if node.type not in {'assignment', 'short_var_declaration', 'assignment_statement', 'variable_declarator'}:
            continue
        left, right = child(node, 'left', 'name'), child(node, 'right', 'value')
        if left is None or right is None or source.text(left) != root:
            continue
        owner = node.parent
        while owner is not None and owner.type not in FUNCTIONS:
            owner = owner.parent
        if owner is None or not (owner.start_byte == test['span']['start_byte']
                                 and owner.end_byte == test['span']['end_byte']):
            continue
        latest = right
    if latest is None:
        return key, identity
    while latest.type == 'expression_list' and len(latest.named_children) == 1:
        latest = latest.named_children[0]
    if latest.type not in CALLS:
        return key, identity
    fn, _ = call_parts(latest)
    producer = source.text(fn)
    head, *tail = producer.split('.')
    imports = {record['name']: record for record in test.get('support', {}).get('imports', [])}
    origin = imports.get(head)
    resolved = (('import', origin['module'], origin.get('imported_name') or '', *tail)
                if origin else ('file', path, producer))
    constructor_key = ('receiver_producer', resolved, '.'.join(callee.split('.')[1:]))
    return (constructor_key, key[1]), {'canonical': None, 'resolution': 'approximate_receiver_producer',
                                      'producer': resolved, 'original': identity}


def generate(corpus, *, top_k=10, max_candidates=128, max_values=72,
             neighbors=6, max_attempts=8000):
    tests, skipped = corpus['tests'], Counter()
    seeds = {t['id'] for t in tests.values() if t.get('retrieval_rank') and t['retrieval_rank'] <= top_k}
    if not seeds:
        seeds = {t['id'] for t in sorted(tests.values(), key=lambda t: t['id'])[:top_k]}
    groups, identities, sources, tokenized = defaultdict(list), {}, {}, {}
    for donor in engine.expanded_donors(corpus):
        if (not donor.get('literal_known') or not isinstance(donor.get('literal_value'), str)
                or donor.get('role') == 'expected' or engine.expected_only(donor)):
            continue
        value = donor['literal_value']
        if len(value) > 8192:
            skipped['literal_character_budget'] += 1
            continue
        sequence = tokens(value)
        if len(sequence) > 256:
            skipped['literal_token_budget'] += 1
            continue
        tokenized[value] = sequence
        parent = tests[donor['test_id']]
        unit = corpus['sources'][parent['span']['path']]
        if not unit.get('complete_file', True) or unit.get('parse_error'):
            continue
        for port in engine.input_ports(donor):
            key, identity = _port_identity(corpus, donor, port, sources)
            groups[key].append(donor)
            identities[(repr(key), donor['id'])] = identity
    pool, attempts, exhausted = {}, 0, False
    # Order by the nearest retrieved test, so unrelated ports cannot consume
    # the budget before those actually selected by retrieval.
    ordered_groups = sorted(groups.items(), key=lambda pair: (
        min((tests[d['test_id']].get('retrieval_rank') or 99999 for d in pair[1]), default=99999),
        repr(pair[0])))
    for slot, members in ordered_groups:
        if not any(d['test_id'] in seeds for d in members):
            continue
        ordered = sorted(members, key=lambda d: (d['test_id'] not in seeds,
                         tests[d['test_id']].get('retrieval_rank') or 99999, d['id']))
        unique = {}
        for d in ordered:
            unique.setdefault(d['literal_value'], d)
        values = list(unique.values())[:max_values]
        rules = {}
        for source in values:
            seq = tokenized[source['literal_value']]
            nearest = sorted((d for d in values if d['id'] != source['id']), key=lambda d: (
                -difflib.SequenceMatcher(a=seq, b=tokenized[d['literal_value']], autojunk=False).ratio(), d['id']))[:neighbors]
            for destination in nearest:
                for edit in learn(source['literal_value'], destination['literal_value']):
                    rules.setdefault(edit.fingerprint, (edit, source, destination))
        for edit, source, destination in sorted(rules.values(), key=lambda v: (
                len(v[0].pattern), v[0].fingerprint)):
            for target in ordered:
                if target['id'] in {source['id'], destination['id']}:
                    continue
                if not {target['test_id'], source['test_id'], destination['test_id']} & seeds:
                    continue
                if attempts >= max_attempts:
                    exhausted = True
                    break
                attempts += 1
                output = edit.apply(target['literal_value'])
                if output is None:
                    skipped['not_unique_or_unchanged'] += 1
                    continue
                # A transfer should combine source features, not replay a
                # literal already present at this call port.
                if output in unique:
                    skipped['already_observed_literal'] += 1
                    continue
                replacement = encode_literal(output, corpus['language'], target['text'])
                mutation = {'span': target['span'], 'before': target['text'], 'after': replacement}
                cid = engine.stable_id('local_literal_context', target['test_id'], mutation)
                pool.setdefault(cid, {'id': cid, 'base_test_id': target['test_id'],
                    'source_test_ids': sorted({source['test_id'], destination['test_id']}),
                    'language': corpus['language'], 'kind': 'local_literal_context',
                    'rule_id': edit.fingerprint, 'edits': [mutation], 'imports': [],
                    'provenance': {'target_donor_id': target['id'], 'source_donor_ids': [source['id'], destination['id']],
                        'source_before': source['span'], 'source_after': destination['span'],
                        'local_edit': edit.as_dict(), 'input_port': slot,
                        'port_identity_evidence': [identities[(repr(slot), d['id'])]
                                                   for d in (source, destination, target)],
                        'semantic_status': 'unique_local_syntactic_match_only'},
                    'selection': {'edit_size': edit.removed + len(edit.inserted),
                                  'base_retrieval_rank': tests[target['test_id']].get('retrieval_rank')}})
            if exhausted:
                break
        if exhausted:
            break
    bins = defaultdict(deque)
    for candidate in sorted(pool.values(), key=lambda c: (c['selection']['edit_size'], c['id'])):
        bins[candidate['base_test_id']].append(candidate)
    ordered_tests = sorted(bins, key=lambda tid: (tests[tid].get('retrieval_rank') or 99999, tid))
    selected = []
    while bins and len(selected) < max_candidates:
        for tid in ordered_tests:
            if tid in bins:
                selected.append(bins[tid].popleft())
                if not bins[tid]:
                    del bins[tid]
                if len(selected) >= max_candidates:
                    break
    return {'candidates': selected, 'skipped': dict(skipped), 'attempts': attempts,
            'budget_exhausted': exhausted, 'pool_size': len(pool)}
