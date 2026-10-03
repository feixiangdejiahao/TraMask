"""Check a source-derived box/unbox composition across a guest/host boundary.

The generator learns guest factories and host container views from source. This
layer checks the inverse edit structure, the producer's owner, and local value
bindings. A separate scalar-carrier probe checks the representation adapter.
No source/API/task name decides which candidate is a defect.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re

from anchor_retrieval.syntax import CALLS, Source, attr_parts, call_parts, child, walk
from experimental import relation_search_go_ts as neighbors

VERSION = 'checked-guest-carrier-inverse.v1'
POLICY = dict(version=VERSION, language='go',
    contract='an explicit issue sentence says returned functions/closures and composite/container values must stay/remain/be callable',
    generation='source-neighbour guest_result_container only, rebuilt from repository source tests; no old candidate pool',
    static_checks=['single top-level factory with one owned return', 'byte-exact clone except fresh name and box around returned closure',
                   'producer lookup owner traces to the same guest program', 'all projected uses keep one local value binding',
                   'source host-view imports and selector are checked', 'source expected expressions are untouched'],
    precondition='separate native scalar-box projection probe; failed or unavailable probes do not become defect reports',
    ordering='source retrieval rank, source position, mapping/sequence kind, member and program hash',
    unchanged='complete source test, closure body, other guest statements and all source expected expressions',
    alert='first eligible candidate fails twice with source controls and exact transport; independent full-test audit still required',
    forbidden_inputs=['known witness IDs', 'old candidate lists', 'runtime outcomes during generation', 'audit labels', 'reference code'],
    limitations=['bounded Go-like guest syntax', 'local source binding checks, not a whole-language proof',
                 'a failed adapter probe can hide a real defect and remains an explicit miss',
                 'additional guest globals and opaque host effects require whole-test audit'])


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def contract(issue):
    facts = []
    for match in re.finditer(r'[^.!?\n]+[.!?]?', issue):
        sentence = match.group().strip()
        text = sentence.lower().replace('`', '')
        if (re.match(r'^(?:[-*]\s*)?returned\b', text)
                and not re.search(r'\b(?:not|never|except|unless|only|when|if)\b', text)
                and re.search(r'\b(?:functions?|closures?)\b', text)
                and re.search(r'\b(?:composite|container)\b', text)
                and re.search(r'\bmust\s+(?:stay|remain|be)\s+callable[.!]?$', text)):
            facts.append(dict(text=sentence, start=match.start(), end=match.end(),
                              issue_sha256=hashlib.sha256(issue.encode()).hexdigest()))
    return facts


def _exact(source, extent):
    if extent['path'] != source.path:
        return None
    node = source.root.named_descendant_for_byte_range(extent['start_byte'], max(extent['start_byte'], extent['end_byte']-1))
    while node is not None:
        if (node.start_byte, node.end_byte) == (extent['start_byte'], extent['end_byte']):
            return node
        node = node.parent
    return None


def _factory_guard(program, factory):
    found = [row for row in neighbors._guest_factories(program) if row['name'] == factory['name']]
    if found != [factory]:
        raise ValueError('ambiguous_guest_factory')
    tokens = [(m.group(), m.start(), m.end()) for m in neighbors._GUEST_TOKEN.finditer(program)
              if not m.group().isspace() and not m.group().startswith(('//', '/*'))]
    stack, ends = [], {}
    for i, (token, start, _) in enumerate(tokens):
        if start == factory['start'] and stack:
            raise ValueError('factory_is_not_at_guest_module_scope')
        if token in {'(', '[', '{'}:
            stack.append((token, i))
        elif token in {')', ']', '}'}:
            if not stack or {'(': ')', '[': ']', '{': '}'}[stack[-1][0]] != token:
                raise ValueError('guest_delimiter_mismatch')
            _, begin = stack.pop()
            ends[begin] = i
    if stack:
        raise ValueError('guest_delimiter_mismatch')
    nested = []
    root_func = next(i for i, row in enumerate(tokens) if row[1] > factory['start'] and row[0] == 'func')
    for i, (token, start, _) in enumerate(tokens):
        if token != 'func' or i == root_func or not factory['start'] < start < factory['end']:
            continue
        parameters_end = ends.get(i+1)
        body = parameters_end+1 if parameters_end is not None else None
        end = ends.get(body)
        if end is None:
            raise ValueError('nested_guest_function_unresolved')
        nested.append((start, tokens[end][2]))
    returns = [row for row in tokens if row[0] == 'return' and factory['start'] < row[1] < factory['end']
               and not any(start <= row[1] < end for start, end in nested)]
    if len(returns) != 1:
        raise ValueError('factory_has_other_return_paths')
    if any(row[0] == factory['name'] and factory['start'] < row[1] < factory['end'] for row in tokens):
        raise ValueError('factory_name_observed_inside_clone')


def _single_binding(source, unit, name, at):
    bindings = neighbors._bindings(source)
    binding = neighbors._resolve(bindings, name, at)
    if binding is None or not neighbors._contains(unit.body, binding[0]):
        return None
    writes = []
    for node in walk(unit.body):
        if node.type in {'short_var_declaration', 'assignment_statement', 'var_spec'}:
            left = child(node, 'left', 'name')
            if left is not None:
                writes.extend(part for part in walk(left) if part.type == 'identifier' and source.text(part) == name)
    if len(writes) != 1 or writes[0].start_byte != binding[0].start_byte:
        return None
    return binding


def _owner_reaches_program(source, unit, owner, at, literal, seen=None):
    seen = set() if seen is None else set(seen)
    if owner in seen or len(seen) >= 12:
        return False
    seen.add(owner)
    binding = _single_binding(source, unit, owner, at)
    if binding is None:
        return False
    value = binding[1]
    if neighbors._contains(value, literal):
        return True
    if value.type not in CALLS:
        return False
    callee, arguments = call_parts(value)
    path = neighbors._path(source, callee)
    return (path is not None and len(path) == 2 and not arguments
            and _owner_reaches_program(source, unit, path[0], value, literal, seen))


def check(source, sources, unit, row):
    """Validate independently of the metadata fields used to construct edits."""
    edits = row['edits']
    inputs = [edit for edit in edits if edit.get('role') == 'input']
    bindings = [edit for edit in edits if edit.get('role') == 'binding']
    projections = [edit for edit in edits if edit.get('role') == 'projection']
    if len(inputs) != 1 or len(bindings) != 1 or not projections or len(edits) != 2+len(projections):
        raise ValueError('unexpected_edit_roles')
    for edit in edits:
        node = _exact(source, edit['span'])
        if node is None or source.text(node) != edit['before'] or not neighbors._contains(unit.body, node):
            raise ValueError('edit_source_or_test_scope_mismatch')
    literal = _exact(source, inputs[0]['span'])
    symbol = _exact(source, bindings[0]['span'])
    if literal.type != 'raw_string_literal' or symbol.type != 'interpreted_string_literal':
        raise ValueError('guest_or_lookup_literal_unresolved')
    program = inputs[0]['before'][1:-1]
    factory = row['evidence']['factory']
    _factory_guard(program, factory)
    if neighbors._constant(source, symbol) != (True, factory['name']):
        raise ValueError('lookup_does_not_name_factory')
    fresh = json.loads(bindings[0]['after'])
    if not re.fullmatch(r'[A-Za-z_]\w*', fresh) or re.search(r'\b'+re.escape(fresh)+r'\b', program):
        raise ValueError('fresh_guest_symbol_is_not_fresh')
    relation = row['relation_target']
    member = relation['member']
    if relation['container_kind'] == 'sequence' and type(member) is int and member in {0, 1}:
        before, after = '['+'0, '*member, ']'
    elif relation['container_kind'] == 'mapping' and isinstance(member, str):
        before, after = '{'+json.dumps(member)+': ', '}'
    else:
        raise ValueError('unsupported_guest_carrier')
    start, end = factory['start'], factory['end']
    a, b = factory['return_start'], factory['return_end']
    clone = fresh+program[start+len(factory['name']):a]+before+program[a:b]+after+program[b:end]
    if inputs[0]['after'] != '`'+program+'\n'+clone+'\n`':
        raise ValueError('clone_changes_more_than_the_boxed_return')
    lookup = symbol.parent
    while lookup is not None and lookup.type not in CALLS:
        lookup = lookup.parent
    lookup_fn, _ = call_parts(lookup) if lookup is not None else (None, [])
    lookup_path = neighbors._path(source, lookup_fn)
    if lookup_path is None or len(lookup_path) != 2 or not _owner_reaches_program(
            source, unit, lookup_path[0], lookup, literal):
        raise ValueError('lookup_owner_does_not_trace_to_guest_program')
    product = symbol.parent
    while product is not None and product.type != 'short_var_declaration':
        product = product.parent
    if product is None:
        raise ValueError('direct_producer_declaration_required')
    names, rhs = neighbors._go_results(source, product)
    if len(names) < 2 or rhs is None or rhs == lookup:
        raise ValueError('direct_factory_invocation_required')
    fn, _ = call_parts(rhs)
    receiver, _ = attr_parts(fn) if fn is not None else (None, None)
    if receiver is None or not neighbors._contains(receiver, lookup):
        raise ValueError('producer_does_not_invoke_the_lookup_value')
    value_name = source.text(names[0])
    if _single_binding(source, unit, value_name, projections and _exact(source, projections[0]['span'])) is None:
        raise ValueError('result_binding_is_not_unique')
    view = row['evidence']['host_view']
    donor = sources.get(view['source']['path'])
    if donor is None or donor.data[view['source']['start_byte']:view['source']['end_byte']].decode() != view['source_text']:
        raise ValueError('host_view_source_changed')
    verified_views = neighbors._go_array_views([donor])
    if not any(value == view for value in verified_views):
        raise ValueError('host_view_is_not_source_derived')
    suffix = view['base_suffix']+'['+json.dumps(member)+']'
    for alias, imported in view['imports'].items():
        matched = next((name for name, value in source.imports.items() if value == imported), None)
        if matched is None:
            raise ValueError('host_view_import_mismatch')
        suffix = re.sub(r'\b'+re.escape(alias)+r'\.', matched+'.', suffix)
    for edit in projections:
        node = _exact(source, edit['span'])
        if (node.type != 'identifier' or edit['before'] != value_name
                or edit['after'] != '('+value_name+')'+suffix or node.start_byte <= product.end_byte):
            raise ValueError('projection_is_not_the_inverse_source_view')
        current = node.parent
        while current is not None and current != unit.body:
            if current.type in {'func_literal', 'function_declaration', 'unary_expression'}:
                raise ValueError('captured_or_addressed_result_use')
            current = current.parent
    uses = [node for node in walk(unit.body) if node.type == 'identifier' and source.text(node) == value_name
            and node.start_byte > product.end_byte
            and (binding := neighbors._resolve(neighbors._bindings(source), value_name, node)) is not None
            and binding[0].start_byte == names[0].start_byte]
    if {node.start_byte for node in uses} != {edit['span']['start_byte'] for edit in projections}:
        raise ValueError('result_uses_are_not_all_projected')
    expected = neighbors._expected_regions(source)
    if any(edit['span']['start_byte'] < high and low < edit['span']['end_byte'] for edit in edits for low, high in expected):
        raise ValueError('source_expected_value_changed')
    # This is an adapter probe, not a defect witness. Add a fresh scalar box,
    # fetch it without invoking a function, project through the same host type,
    # and stop before the original result observers.
    probe_input = dict(inputs[0], after='`'+program+'\n'+fresh+':='+before+'0'+after+'\n`')
    getter = source.text(receiver)
    relative_start, relative_end = symbol.start_byte-receiver.start_byte, symbol.end_byte-receiver.start_byte
    getter_bytes = getter.encode()
    getter = (getter_bytes[:relative_start]+bindings[0]['after'].encode()+getter_bytes[relative_end:]).decode()
    cut = dict(path=source.path, start_byte=product.start_byte, end_byte=unit.body.end_byte-1)
    probe_tail = dict(span=cut, before=source.data[cut['start_byte']:cut['end_byte']].decode(),
                      after='_ = ('+getter+')'+suffix+'\n', role='carrier_precondition')
    if inputs[0]['span']['end_byte'] > cut['start_byte']:
        raise ValueError('guest_program_not_before_producer')
    return dict(factory=factory, guest_fresh_name=fresh, host_suffix=suffix,
                original_return_sha256=hashlib.sha256(program[a:b].encode()).hexdigest(),
                producer_span=neighbors._span(source, product), projected_uses=len(projections),
                relation='host_project(guest_box(returned_closure)) preserves the original callable value contract',
                probe_edits=[probe_input, probe_tail])


def generate(corpus, frontend, issue, *, limit=16):
    facts = contract(issue)
    empty = dict(version=VERSION, candidates=[], pairs=[], total_candidates=0, skipped=[], contract=facts)
    if corpus['language'] != 'go':
        return dict(empty, status='language_unsupported')
    if not facts:
        return dict(empty, status='no_explicit_returned_carrier_contract')
    sources, tests = {}, defaultdict(dict)
    for identifier, test in corpus['tests'].items():
        path = test['span']['path']
        row = corpus['sources'][path]
        if row.get('origin') != 'repository' or row.get('parse_error'):
            continue
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:'+path)
        sources.setdefault(path, Source(path, row['code'], 'go', 'repository'))
        tests[path][test.get('definition_span', test['span'])['start_byte']] = (identifier, test)
    views = []
    for view in neighbors._go_array_views(list(sources.values())):
        position = view['source']
        owners = [(identifier, test) for identifier, test in corpus['tests'].items()
                  if test['span']['path'] == position['path'] and test['span']['start_byte'] <= position['start_byte']
                  and position['end_byte'] <= test['span']['end_byte']]
        if owners:
            views.append((view, min(owners, key=lambda pair: pair[1]['span']['end_byte']-pair[1]['span']['start_byte'])[0]))
    donor_for = {digest(view): owner for view, owner in views}
    proposals, skipped = [], []
    for path, source in sorted(sources.items()):
        units = {unit.node.start_byte: unit for unit in neighbors._tests(source)}
        for row in neighbors._guest_container_neighbors(source, [], [view for view, _ in views]):
            matched = tests[path].get(row['test_span']['start_byte'])
            if matched is None:
                continue
            base, test = matched
            try:
                certificate = check(source, sources, units[row['test_span']['start_byte']], row)
            except (ValueError, KeyError, TypeError, IndexError) as error:
                skipped.append(dict(base_test_id=base, reason=str(error)))
                continue
            donor = donor_for[digest(row['evidence']['host_view'])]
            metadata = dict(base_test_id=base, source_test_ids=list(dict.fromkeys([base, donor])), imports=[],
                            generator=VERSION, source_evidence=dict(contract=facts, inverse_certificate={
                                key:value for key,value in certificate.items() if key != 'probe_edits'},
                                source_host_view=row['evidence']['host_view']))
            candidate = dict(metadata, id='inverse_'+digest([VERSION, base, row['edits']])[:24], edits=row['edits'],
                operator='checked_guest_result_carrier', kind='declared_carrier_composition',
                oracle_status='declared_contract_and_checked_inverse_pending_native_probe')
            probe = dict(metadata, id='carrierprobe_'+digest([VERSION, base, certificate['probe_edits']])[:24],
                edits=certificate['probe_edits'], operator='scalar_carrier_precondition', kind='adapter_precondition',
                oracle_status='precondition_only_never_a_defect_alert')
            proposals.append(dict(candidate=candidate, probe=probe, order=[test.get('retrieval_rank') or 100000,
                path, test['span']['start_byte'], row['relation_target']['container_kind'],
                str(row['relation_target']['member']), candidate['id']]))
    unique = {}
    for pair in sorted(proposals, key=lambda pair: pair['order']):
        unique.setdefault(digest([pair['candidate']['base_test_id'], pair['candidate']['edits']]), pair)
    ranking = list(unique.values())
    return dict(version=VERSION, status='source_candidates', pairs=ranking[:limit],
                total_candidates=len(ranking), selected=min(len(ranking), limit), skipped=skipped, contract=facts)
