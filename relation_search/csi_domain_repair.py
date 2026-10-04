"""Propose one bounded CSI-u input repair while preserving the complete oracle.

Public sender grammar supplies the repair hypothesis. Source-bound input sites
supply locations. Neither a repair nor full-test model support proves an
otherwise unresolved receiver/protocol association.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import re

from combination_testing.protocol import Packet
from relation_search.candidate_edit_transport import rewrite_view
from relation_search.oracle import preview

VERSION = 'source-bound-shifted-primary-repair.v1'
POLICY = dict(version=VERSION, language='python',
    premise='A complete source-bound CSI-u packet has ASCII uppercase primary 65..90, wire modifiers in 1..256, and an already present Shift bit ((wire_modifiers-1)&1).',
    repair='Replace only the primary with primary+32. Do not add modifiers, alternate codes, associated text or phase.',
    source_pool='All frozen historical full-test source attempts; no outcome, old semantic judgment or audit label selects proposals.',
    oracle='Preserve all original historical candidate setup and assertions byte-for-byte except the one source-bound input primary.',
    ordering='Original attempt order, then input literal byte span; no outcome-based replacement.',
    unknown='Retain unresolved-domain proposals for fresh full-test review; unresolved source domain cannot enter native execution.',
    limitation='A source-domain repair hypothesis is neither a valid whole test nor a detected defect.',
    authority='https://sw.kovidgoyal.net/kitty/keyboard-protocol/#key-codes')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_sha(value):
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')))


def _span(code, node):
    lines = code.encode().splitlines(keepends=True)
    return sum(map(len, lines[:node.lineno-1])) + node.col_offset, sum(map(len, lines[:node.end_lineno-1])) + node.end_col_offset


def _verify_receipt(code, receipt):
    data = code.encode()
    a, b = receipt['start_byte'], receipt['end_byte']
    return (receipt['path'] == '<modified_test>' and receipt['source_sha256'] == sha(code)
            and 0 <= a < b <= len(data) and data[a:b].decode() == receipt['text'])


def opportunities(payload, source_gate):
    """Enumerate by packet and exact bound-input receipts, never gate outcome."""
    if payload.get('language') != 'python':
        return dict(opportunities=[], unknowns=[], status='language_outside_scope')
    code = payload['modified_test']
    if source_gate['modified_test_sha256'] != sha(code):
        raise ValueError('Source gate refers to different complete test bytes')
    tree = ast.parse(code)
    proposals, unknowns, seen = [], [], set()
    for check in source_gate.get('checks', []):
        value = check.get('value')
        packet = Packet.parse(value) if isinstance(value, str) else None
        if packet is None or not re.fullmatch(r'[0-9]+u', packet.key):
            continue
        primary = int(packet.key[:-1])
        if not 65 <= primary <= 90 or not 1 <= packet.modifiers <= 256 or not ((packet.modifiers-1) & 1):
            continue
        # A direct feed call or a proved helper argument supplies the actual
        # input location. An equal expected/sample literal elsewhere cannot.
        locations = []
        call = check.get('call_receipt', {})
        if call.get('path') == '<modified_test>':
            if not _verify_receipt(code, call):
                raise ValueError('Input call receipt differs')
            matches = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and _span(code, n) == (call['start_byte'], call['end_byte'])]
            if len(matches) == 1:
                locations += [n for n in [*matches[0].args, *(k.value for k in matches[0].keywords)]
                              if isinstance(n, ast.Constant) and n.value == value]
        for link in check.get('binding_chain', []):
            for argument in link.get('arguments', []):
                receipt = argument.get('actual', {})
                if receipt.get('path') != '<modified_test>':
                    continue
                if not _verify_receipt(code, receipt):
                    raise ValueError('Input helper-argument receipt differs')
                locations += [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and n.value == value
                              and _span(code, n) == (receipt['start_byte'], receipt['end_byte'])]
        unique = {_span(code, node): node for node in locations}
        if len(unique) != 1:
            unknowns.append(dict(value=value, reason='input_literal_binding_missing_or_ambiguous'))
            continue
        (start, end), node = next(iter(unique.items()))
        if (start, end) in seen:
            continue
        seen.add((start, end))
        literal = code.encode()[start:end].decode()
        digits = list(re.finditer(r'\[([0-9]+)(?=[:;u])', literal))
        if len(digits) != 1 or int(digits[0].group(1)) != primary:
            unknowns.append(dict(value=value, reason='primary_literal_encoding_unresolved'))
            continue
        a, b = digits[0].span(1)
        rewritten = literal[:a] + str(primary+32) + literal[b:]
        repaired_value = re.sub(r'(?<=\x1b\[)[0-9]+', str(primary+32), value, count=1)
        if ast.literal_eval(rewritten) != repaired_value:
            raise ValueError('Literal rewrite changes more than the primary')
        # Compare every parsed field as an extra check; suffix and other raw
        # fields also remain byte-identical in repaired_value above.
        new_packet = Packet.parse(repaired_value)
        before, after = packet.as_dict(), new_packet.as_dict()
        if {k: v for k, v in before.items() if k != 'key'} != {k: v for k, v in after.items() if k != 'key'}:
            raise ValueError('Repair changed another packet coordinate')
        repaired = (code.encode()[:start] + rewritten.encode() + code.encode()[end:]).decode()
        ast.parse(repaired)
        proposals.append(dict(start_byte=start, end_byte=end, literal_before=literal, literal_after=rewritten,
            value_before=value, value_after=repaired_value, primary_before=primary, primary_after=primary+32,
            wire_modifiers=packet.modifiers, original_complete_test_sha256=sha(code),
            repaired_complete_test_sha256=sha(repaired), repaired_test=repaired,
            input_binding=dict(call_receipt=call, binding_chain=check.get('binding_chain', [])),
            semantic_status='hypothesis_pending_fresh_full_test_and_source_domain_review'))
    proposals.sort(key=lambda row: (row['start_byte'], row['end_byte']))
    return dict(status='source_hypotheses' if proposals else 'no_bound_repair_opportunity',
                opportunities=proposals, unknowns=unknowns)


def construct(corpus, historical_candidate, payload, proposal):
    """Compose a literal repair with authoritative existing source edits.

    The inverse coordinate map allows a new literal outside an earlier edit.
    A literal crossing an edit boundary abstains instead of widening the edit.
    """
    prior = rewrite_view(historical_candidate)
    if preview(corpus, prior) != payload['modified_test']:
        raise ValueError('Historical candidate does not reproduce complete reviewed test')
    if proposal['original_complete_test_sha256'] != sha(payload['modified_test']):
        raise ValueError('Repair proposal test differs')
    base = corpus['tests'][prior['base_test_id']]
    path = base['span']['path']
    original = corpus['sources'][path]['code']
    original_test = original.encode()[base['span']['start_byte']:base['span']['end_byte']].decode()
    if original_test != payload['original_test']:
        raise ValueError('Original complete-test bytes differ')
    edits = copy.deepcopy(prior['edits'])
    same_file = sorted([(i, e) for i, e in enumerate(edits) if e['span']['path'] == path],
                       key=lambda pair: pair[1]['span']['start_byte'])
    delta, ranges, previous_end = 0, [], -1
    for index, edit in same_file:
        a, b = edit['span']['start_byte'], edit['span']['end_byte']
        if a < previous_end or original.encode()[a:b].decode() != edit['before']:
            raise ValueError('Historical edit span mismatch or overlap')
        if a < base['span']['start_byte'] or b > base['span']['end_byte']:
            raise ValueError('Repair constructor requires edits within the complete base test')
        start = a - base['span']['start_byte'] + delta
        end = start + len(edit['after'].encode())
        ranges.append((start, end, index, delta))
        delta += len(edit['after'].encode()) - (b-a)
        previous_end = b
    a, b = proposal['start_byte'], proposal['end_byte']
    overlaps = [r for r in ranges if a < r[1] and r[0] < b]
    if overlaps:
        if len(overlaps) != 1 or not (overlaps[0][0] <= a < b <= overlaps[0][1]):
            raise ValueError('Repair literal crosses historical edit boundary')
        start, _, index, _ = overlaps[0]
        data = edits[index]['after'].encode()
        if data[a-start:b-start].decode() != proposal['literal_before']:
            raise ValueError('Composed repair literal differs')
        edits[index]['after'] = (data[:a-start] + proposal['literal_after'].encode() + data[b-start:]).decode()
    else:
        shift = sum(len(edits[i]['after'].encode()) - (edits[i]['span']['end_byte']-edits[i]['span']['start_byte'])
                    for start, end, i, _ in ranges if end <= a)
        old_a, old_b = base['span']['start_byte'] + a-shift, base['span']['start_byte'] + b-shift
        if original.encode()[old_a:old_b].decode() != proposal['literal_before']:
            raise ValueError('Inverse repair coordinate differs')
        edits.append(dict(span=dict(path=path, start_byte=old_a, end_byte=old_b),
                          before=proposal['literal_before'], after=proposal['literal_after'], role='input'))
    result = dict(language='python', kind='source_bound_csi_primary_repair', execution_lane='relation_search',
        base_test_id=prior['base_test_id'], edits=edits, imports=copy.deepcopy(prior.get('imports', [])),
        source_test_ids=copy.deepcopy(prior.get('source_test_ids', [])),
        oracle=dict(mode='retain_all', source_test_id=prior['base_test_id'],
                    applicability='requires_fresh_complete_test_review_and_proved_source_domain'),
        relation=dict(version=VERSION, primary_before=proposal['primary_before'], primary_after=proposal['primary_after'],
                      wire_modifiers=proposal['wire_modifiers'], repair_span=[a, b]),
        provenance=dict(historical_candidate_sha256=canonical_sha(historical_candidate),
                        historical_complete_test_sha256=proposal['original_complete_test_sha256'],
                        repaired_complete_test_sha256=proposal['repaired_complete_test_sha256'],
                        input_binding=proposal['input_binding'], retained_oracle='all historical full-test assertions'))
    result['csi_repair'] = {k: v for k, v in proposal.items() if k != 'repaired_test'}
    result['id'] = 'csirepair_' + canonical_sha(result)[:24]
    if preview(corpus, result) != proposal['repaired_test']:
        raise ValueError('Repaired source edits do not preserve exact complete test')
    return result
