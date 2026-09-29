"""Deterministic, candidate-specific source evidence for local oracle reasoning.

Reparse and rebind the changed source before following calls. The result is a
partial *may* dependence explanation, not an inferred specification or proof of
runtime order. Full declarations and source controls are never text-truncated.
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import ATTRS, FUNCTIONS, Source, attr_parts, child, units, walk
from anchor_retrieval.index import Index
from relation_search.instrument import _program_edits
from relational_gap.frontend import extract_frontend


VERSION = 'candidate_oracle_evidence.v1'


def _text(sources, span):
    return sources[span['path']]['code'].encode()[span['start_byte']:span['end_byte']].decode()


def _key(span):
    return span['path'], span['start_byte'], span['end_byte']


def _overlap(a, b):
    if not a or not b or a['path'] != b['path']:
        return False
    if a['start_byte'] == a['end_byte']:
        return b['start_byte'] <= a['start_byte'] <= b['end_byte']
    return a['start_byte'] < b['end_byte'] and b['start_byte'] < a['end_byte']


def _sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _dedup(rows):
    return list({json.dumps(row, sort_keys=True): row for row in rows}.values())


@lru_cache(maxsize=2)
def _source_inventory(rows):
    # Cached syntax is read-only. The changed owner is reparsed separately.
    return tuple(Source(*row) for row in rows)


def _modified_sources(corpus, candidate):
    """Validate edits, preserve original metadata, and bind added import aliases."""
    test = corpus['tests'][candidate['base_test_id']]
    owner = test['span']['path']
    original = corpus['sources'][owner]['code'].encode()
    data = original
    program_edits = _program_edits(candidate)
    edits = sorted(program_edits, key=lambda e: (e['span']['start_byte'], e['span']['end_byte']))
    original_indices = {_key(e['span']): i for i,e in enumerate(program_edits)}
    previous = -1
    changes = []
    delta = 0
    for index, edit in enumerate(edits):
        span = edit['span']
        if span['path'] != owner or not (test['span']['start_byte'] <= span['start_byte'] <= span['end_byte'] <= test['span']['end_byte']):
            raise ValueError('candidate edit outside selected test')
        if span['start_byte'] < previous:
            raise ValueError('overlapping candidate edits')
        previous = span['end_byte']
        if original[span['start_byte']:span['end_byte']].decode() != edit['before']:
            raise ValueError('candidate edit does not match original source')
        start = span['start_byte'] + delta
        after_bytes = len(edit['after'].encode())
        changes.append(dict(id='E'+str(original_indices[_key(span)]), original_edit_index=original_indices[_key(span)], original_span=span,
                            span=dict(path=owner, start_byte=start, end_byte=start+after_bytes),
                            before=edit['before'], after=edit['after'], role=edit.get('role', 'input')))
        delta += after_bytes - (span['end_byte'] - span['start_byte'])
    for edit in reversed(edits):
        s = edit['span']
        data = data[:s['start_byte']] + edit['after'].encode() + data[s['end_byte']:]
    rows = tuple((path, row['code'], row.get('language', corpus['language']),
                  row.get('origin', 'repository'), row.get('step'), row.get('written_path'))
                 for path, row in sorted(corpus['sources'].items()))
    originals = _source_inventory(rows)
    old = next(source for source in originals if source.path == owner)
    current = Source(old.path, data.decode(), old.language, old.origin, old.step, old.written_path)
    sources = [current if source.path == owner else source for source in originals]
    imports, unknowns = [], []
    for record in candidate.get('imports', []):
        alias, module, name = record['name'], record['module'], record.get('imported_name')
        source_path = record.get('source_path', owner)
        lookup = corpus['sources'].get(source_path, {}).get('written_path') or source_path
        # Generated aliases can originate in a donor in a different directory.
        # Resolve relative imports against that donor, then rebase to the owner.
        bound_module = module
        if current.language == 'typescript' and module.startswith('.'):
            target = posixpath.normpath(posixpath.join(posixpath.dirname(lookup), module))
            bound_module = posixpath.relpath(target, posixpath.dirname(current.lookup_path) or '.')
            if not bound_module.startswith('.'):
                bound_module = './' + bound_module
        elif current.language == 'python' and module.startswith('.') and lookup != current.lookup_path:
            dots = len(module) - len(module.lstrip('.'))
            base = posixpath.dirname(lookup)
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            bound_module = posixpath.join(base, module[dots:].replace('.', '/')).replace('/', '.')
        if alias in current.imports and current.imports[alias] != (bound_module, name):
            unknowns.append(dict(reason='added_import_shadows_original_binding', alias=alias))
        current.imports[alias] = (bound_module, name)
        imports.append(dict(alias=alias, module=module, imported_name=name,
                            resolution_module=bound_module, source_path=source_path))
    return sources, current, changes, imports, unknowns


def _local_ref(name, before, bindings):
    available = [b for b in bindings if b['simple_name'] and b['name'] == name and b['definition_end'] <= before]
    if not available:
        return None
    row = max(available, key=lambda b: b['definition_end'])
    if row.get('contexts'):
        return None
    seen = set()
    while row.get('alias_name') and row['id'] not in seen:
        seen.add(row['id'])
        prior = [b for b in bindings if b['simple_name'] and b['name'] == row['alias_name']
                 and b['definition_end'] <= row['span']['start_byte']]
        if not prior:
            break
        row = max(prior, key=lambda b: b['definition_end'])
        if row.get('contexts'):
            return None
    return row['id']


def _field_write_edges(source, bindings, changes, calls):
    """Link edited local field stores to uses of the same versioned receiver.

    This is deliberately a may-state edge. A callee may ignore/overwrite the
    field; its declaration is supplied for semantic reasoning. Distinct local
    object bindings and later rebindings are not conflated by field spelling.
    """
    edges, unknowns = [], []
    nodes = {(n.start_byte, n.end_byte): n for n in walk(source.root)}
    for binding in bindings:
        if binding['simple_name']:
            continue
        modified = [c for c in changes if c['role'] != 'semantic_expected' and _overlap(c['span'], binding['span'])]
        if not modified:
            continue
        target = binding.get('target') or {}
        extent = target.get('span', {})
        node = nodes.get((extent.get('start_byte'), extent.get('end_byte')))
        if node is None or node.type not in ATTRS:
            continue
        receiver, field = attr_parts(node)
        if receiver is None or receiver.type != 'identifier':
            unknowns.append(dict(reason='edited_field_receiver_not_simple_local', span=binding['span']))
            continue
        origin = _local_ref(source.text(receiver), node.start_byte, bindings)
        if origin is None:
            unknowns.append(dict(reason='edited_field_receiver_binding_unknown', span=binding['span']))
            continue
        for call in calls:
            if call['span']['start_byte'] < binding['span']['end_byte']:
                continue
            refs = [call.get('receiver_binding')] + [a.get('binding') for a in call.get('arguments', [])]
            if any(ref and ref.get('origin_binding_id') == origin and ref.get('resolution') == 'local_value_binding' for ref in refs):
                for change in modified:
                    edges.append(dict(source=change['id'], target='C:'+call['id'],
                                      kind='same_local_binding_after_field_write_may',
                                      field=source.text(field), binding_id=origin,
                                      ordering='lexical_only_not_runtime_happens_before'))
    return edges, unknowns


def _resolved_targets(call, functions, sources, module_resolution):
    targets = []
    for target in call['targets']:
        if not target.get('resolved') or target['function_id'] not in functions:
            continue
        if target['reason'] == 'package_symbol':
            # Legacy package-name matching is not enough to establish a Go
            # import binding: different module directories can share a name.
            source = sources[call['span']['path']]
            imported = source.imports.get(call['callee'].split('.', 1)[0])
            target_path = functions[target['function_id']]['span']['path']
            target_source = sources[target_path]
            paths = []
            for root, module in (module_resolution.get('go_modules') or {}).items():
                root = root.rstrip('/')
                directory = posixpath.dirname(target_source.lookup_path)
                if not root or directory == root or directory.startswith(root+'/'):
                    relative = posixpath.relpath(directory or '.', root or '.')
                    paths.append(module.rstrip('/') + (('/'+relative) if relative != '.' else ''))
            if not imported or imported[0] not in paths:
                continue
        targets.append(target)
    return targets


def _signature(call):
    targets = tuple(sorted(t['function_id'] for t in call.get('targets', []) if t.get('resolved')))
    return targets if len(targets) == 1 else ()


def _control_tests(frontend, calls, seed_ids, changes, base_id, max_per_call=2):
    """Retrieve source tests with an exact argument and resolved callee match.

    This is evidence retrieval, not a claim that the control has a valid oracle.
    No issue labels, evaluation results or model cache are consulted.
    """
    controls = []
    for call in calls:
        signature = _signature(call)
        if call['id'] not in seed_ids or not signature:
            continue
        values = {a['text'] for a in call.get('arguments', [])
                  if any(_overlap(c['span'], a['span']) for c in changes if c['role'] != 'semantic_expected')}
        if not values:
            continue
        matches = []
        for original in frontend.get('calls', []):
            if original.get('test_id') == base_id or _signature(original) != signature:
                continue
            shared = sorted(values & {a['text'] for a in original.get('arguments', [])})
            if shared:
                matches.append((original['span']['path'], original['span']['start_byte'], original['test_id'], shared))
        seen = set()
        for _, _, test_id, shared in sorted(matches):
            if test_id in seen:
                continue
            seen.add(test_id)
            controls.append(dict(test_id=test_id, reason='same_resolved_callee_and_changed_argument',
                                 call_id=call['id'], matched_arguments=shared))
            if len(seen) >= max_per_call:
                break
    return _dedup(controls)


def build_evidence(corpus, frontend, candidate, *, max_bytes=48000, declaration_depth=1):
    """Return source-derived prompt evidence for one complete candidate test.

    ``rendered`` is directly usable in an oracle prompt. ``status=over_budget``
    reports a limit without truncating code. The caller must supply the full
    modified test separately. All spans in rebound calls refer to the modified
    source; declarations have hashes. This function performs no model calls.
    """
    sources, owner, changes, imports, unknowns = _modified_sources(corpus, candidate)
    resolution = frontend.get('module_resolution', {})
    try:
        current = extract_frontend(sources, test_ids=[candidate['base_test_id']],
            max_production_depth=declaration_depth+1, max_production_units=128,
            module_aliases=resolution.get('aliases'), module_base_url=resolution.get('base_url'),
            go_modules=resolution.get('go_modules'))
    finally:
        # Index's class-level memoization otherwise retains every temporary
        # modified repository. Clearing cached queries changes no source facts.
        for method in (Index.module_paths, Index.reach, Index.field_factors):
            method.cache_clear()
    tests = current['tests']
    if not tests:
        unknowns.append(dict(reason='modified_test_owner_not_recovered'))
    if owner.root.has_error:
        unknowns.append(dict(reason='modified_source_parse_error', path=owner.path))
    calls = current['calls']
    observations = {q['id']: q for q in current['observations']}
    bindings = current['bindings']
    functions = {f['id']: f for f in current['functions']}
    parsed = {source.path:source for source in sources}
    for call in current['calls'] + current['production_calls']:
        reliable = {t['function_id'] for t in _resolved_targets(call, functions, parsed, resolution)}
        for target in call['targets']:
            if target.get('resolved') and target['reason'] == 'package_symbol' and target['function_id'] not in reliable:
                target['resolved'] = False
                unknowns.append(dict(reason='go_import_target_not_confirmed_by_module_path',
                                     call_id=call['id'], function_id=target['function_id']))
    seeds = set()
    edges = []
    input_changes = [c for c in changes if c['role'] != 'semantic_expected']
    for change in input_changes:
        for call in calls:
            if _overlap(change['span'], call['span']):
                seeds.add(call['id'])
                edges.append(dict(source=change['id'], target='C:'+call['id'], kind='modified_span_overlap'))
        for value in current['values']:
            if _overlap(change['span'], value['span']):
                for use in value.get('input_slots', []) + value.get('argument_slots', []):
                    seeds.add(use['call_id'])
                    edges.append(dict(source=change['id'], target='C:'+use['call_id'],
                                      kind='modified_value_use_may', slot=use['slot']))
        changed_bindings = {b['id'] for b in bindings if _overlap(change['span'], b['span'])}
        for call in calls:
            refs = [call.get('receiver_binding')] + [a.get('binding') for a in call.get('arguments', [])]
            if any(ref and {ref.get('binding_id'), ref.get('origin_binding_id')} & changed_bindings for ref in refs):
                seeds.add(call['id'])
                edges.append(dict(source=change['id'], target='C:'+call['id'], kind='modified_local_binding_use_may'))
    field_edges, field_unknowns = _field_write_edges(owner, bindings, input_changes, calls)
    edges.extend(field_edges)
    unknowns.extend(field_unknowns)
    seeds.update(e['target'][2:] for e in field_edges)
    qids = {qid for call in calls if call['id'] in seeds for qid in call['observation_ids']}
    for change in input_changes:
        qids.update(qid for qid, q in observations.items() if _overlap(change['span'], q.get('observed', {}).get('span')))
    relevant_calls = [call for call in calls if call['id'] in seeds or set(call['observation_ids']) & qids]
    if not seeds:
        unknowns.append(dict(reason='no_modified_input_to_call_link'))
    contexts = {}

    def include(sources_map, span, role, identifier=None):
        if not span or span.get('path') not in sources_map:
            unknowns.append(dict(reason='required_source_span_missing', role=role, id=identifier))
            return
        key = (_sha(sources_map[span['path']]['code']),) + _key(span)
        row = contexts.setdefault(key, dict(span=span, code=_text(sources_map, span), roles=[],
                                    source_sha256=_sha(sources_map[span['path']]['code'])))
        if role not in row['roles']:
            row['roles'].append(role)
        if identifier:
            row.setdefault('ids', [])
            if identifier not in row['ids']:
                row['ids'].append(identifier)

    controls = [dict(test_id=tid, reason='candidate_source_test') for tid in candidate.get('source_test_ids', [])
                if tid != candidate['base_test_id']]
    controls.extend(_control_tests(frontend, calls, seeds, changes, candidate['base_test_id']))
    controls = _dedup(controls)
    for control in controls:
        record = corpus['tests'].get(control['test_id'])
        if record:
            include(corpus['sources'], record['span'], 'source_control_test', control['test_id'])
    source_test = tests[0] if tests else {}
    for helper in source_test.get('support', {}).get('helpers', []):
        include(current['sources'], helper.get('span'), 'source_test_helper')
    for fixture in source_test.get('support', {}).get('fixtures', []):
        for item in fixture.get('sources', []):
            include(current['sources'], item.get('span'), 'source_fixture')
    for context in candidate.get('source_contexts', []):
        include(corpus['sources'], context.get('span'), 'candidate_source_context')
    # Function-valued arguments can carry essential behavior even when the
    # receiving API (thread/executor/map/etc.) is external. Show exact local
    # declarations without pretending to prove when a callback is invoked.
    callback_references = []
    owner_units, _ = units(owner)
    for call in relevant_calls:
        for argument in call['arguments']:
            name = argument['text']
            if not name.isidentifier():
                continue
            active = [b for b in bindings if b['simple_name'] and b['name'] == name
                      and b['definition_end'] <= argument['span']['start_byte']]
            parameter_names = {p['name'] for test in tests for p in test.get('parameters', [])}
            if active or name in parameter_names:
                continue
            visible = []
            for unit in owner_units:
                if unit.name != name or unit.test or unit.owner:
                    continue
                scope = unit.node.parent
                while scope is not None and scope.type not in FUNCTIONS | {'module', 'program', 'source_file'}:
                    scope = scope.parent
                if scope is not None and (scope.type in {'module','program','source_file'} or
                        scope.start_byte <= call['span']['start_byte'] < scope.end_byte):
                    visible.append(unit)
            if len(visible) == 1:
                unit = visible[0]
                extent = dict(path=owner.path,start_byte=unit.node.start_byte,end_byte=unit.node.end_byte)
                include(current['sources'],extent,'function_valued_argument_declaration',unit.id)
                callback_references.append(dict(call_id=call['id'],argument=name,declaration_id=unit.id,
                    invocation='unknown; function value passed to call',binding='same lexical scope source evidence'))
            elif len(visible) > 1:
                unknowns.append(dict(reason='function_valued_argument_ambiguous',call_id=call['id'],argument=name))
    production = defaultdict(list)
    for call in current['production_calls']:
        production[call['function_id']].append(call)
    # Expand changed-input callees one level. Other producers of the same
    # observation contribute their direct declarations, not unrelated setup
    # transitive closures. Limits remain visible as unknown frontier entries.
    pending = [(call, 0 if call['id'] in seeds else declaration_depth) for call in relevant_calls]
    expanded = {}
    call_records = []
    while pending:
        call, depth = pending.pop(0)
        targets = _resolved_targets(call, functions, parsed, resolution)
        linked = sorted(set(call.get('observation_ids', [])) & qids)
        for qid in linked:
            edges.append(dict(source='C:'+call['id'], target='Q:'+qid, kind='modified_static_slice_may'))
        row = dict(id=call['id'], callee=call['callee'], span=call['span'],
                   code=_text(current['sources'], call['span']), seed=call['id'] in seeds,
                   related_assertions=linked, targets=[], actual_formal=[])
        if len(targets) != 1:
            unknowns.append(dict(reason='modified_callee_unresolved_or_ambiguous', callee=call['callee'], call_id=call['id']))
        else:
            target = targets[0]
            function = functions[target['function_id']]
            include(current['sources'], function['span'], 'candidate_declaration_not_oracle', function['id'])
            row['targets'].append(dict(function_id=function['id'], reason=target['reason']))
            args = {arg['slot']: arg for arg in call['arguments']}
            params = {p['index']: p for p in function['parameters']}
            for binding in call['argument_bindings']:
                if binding['function_id'] == function['id'] and binding['binding_status'] == 'direct_actual_formal':
                    arg, parameter = args[binding['slot']], params[binding['parameter_index']]
                    row['actual_formal'].append(dict(actual=arg['text'], parameter=parameter['name'],
                        slot=binding['slot'], actual_span=arg['span'], function_id=function['id']))
            if depth < expanded.get(function['id'], declaration_depth+1):
                expanded[function['id']] = depth
                if depth < declaration_depth:
                    pending.extend((nested, depth+1) for nested in production[function['id']])
                elif production[function['id']]:
                    unknowns.append(dict(reason='declaration_depth_limit', function_id=function['id']))
        call_records.append(row)
    assertions = [dict(id=qid, span=observations[qid].get('assertion_span') or observations[qid]['span'],
                        code=_text(current['sources'], observations[qid].get('assertion_span') or observations[qid]['span']),
                        observed=observations[qid].get('observed', {}).get('text'),
                        expectation_status='source_expectation_not_semantically_validated') for qid in sorted(qids)]
    if current['stats']['production_budget_reached']:
        unknowns.append(dict(reason='frontend_production_unit_budget', limit=128))
    result = dict(version=VERSION, candidate_id=candidate['id'], source_scope='modified_candidate_static_may_evidence',
        modified_bindings_recomputed=True, full_modified_test_required=True, complete_slice=False,
        changes=changes, added_import_bindings=imports, seed_call_ids=sorted(seeds),
        calls=_dedup(call_records), assertions=assertions, edges=_dedup(edges), controls=controls,
        function_valued_arguments=callback_references,
        original_observation_obligations=candidate.get('impact_evidence', {}).get('obligations', []),
        declarations=list(contexts.values()), unknowns=_dedup(unknowns),
        limits=dict(declaration_depth=declaration_depth, frontend_production_units=128,
                    max_bytes=max_bytes, source_controls_per_call=2),
        analysis_stats=dict(calls=len(calls), relevant_calls=len(relevant_calls),
                            observations=len(observations), related_assertions=len(assertions)))
    result['rendered'] = render_evidence(result)
    result['rendered_bytes'] = len(result['rendered'].encode())
    result['status'] = 'over_budget' if max_bytes is not None and result['rendered_bytes'] > max_bytes else 'ready'
    return result


def _render_obligations(obligations):
    """Intern original graph nodes and paths; keep every offered obligation."""
    if not obligations:
        return []
    paths, nodes, observations, source_paths = {}, {}, {}, {}
    links = []

    def location(span):
        if not span:
            return 'unknown'
        path = span['path']
        source_paths.setdefault(path, 'S'+str(len(source_paths)))
        return source_paths[path]+':'+str(span['start_byte'])+'..'+str(span['end_byte'])

    for item in obligations:
        qid = item['observation_id']
        observations.setdefault(qid, (item, 'O'+str(len(observations))))
        sequence = []
        for node in item.get('path', []):
            key = (node['path'], node['id'])
            nodes.setdefault(key, (node, 'N'+str(len(nodes))))
            sequence.append(nodes[key][1])
        key = (tuple(sequence), tuple(item.get('edge_kinds', [])))
        paths.setdefault(key, 'P'+str(len(paths)))
        links.append('E'+str(item['edit_index'])+' -> '+observations[qid][1]+' via '+paths[key])
    body = ['Original-source unpaired impacts (may dependence; unchanged expected value is not proof it must change):']
    for item, alias in observations.values():
        body.append(alias+' q='+item['observation_id']+' actual='+location(item.get('actual_span'))+
                    ' expected='+location(item.get('expected_span'))+
                    ' expected_dependency='+item.get('expected_dependency_basis','unknown'))
        body.append('  actual: '+str(item.get('observed'))+'; source expected: '+str(item.get('expected')))
    for node, alias in nodes.values():
        body.append(alias+' ['+node['kind']+'] '+location(node)+' '+node.get('text',''))
    for (sequence, kinds), alias in paths.items():
        route = sequence[0] if sequence else 'unknown'
        for kind, target in zip(kinds, sequence[1:]):
            route += ' --'+kind+'--> '+target
        body.append(alias+' '+route)
    body.extend(dict.fromkeys(links))
    return ['ORIGINAL '+alias+'='+path for path,alias in source_paths.items()] + body


def render_evidence(evidence):
    """Compact raw-source facts; no generated relationship descriptions."""
    lines = ['Candidate source reanalysed after input edits. Edges are static may dependencies.',
             'Declarations describe candidate code, not required behavior. Read with the complete modified test.']
    for binding in evidence['added_import_bindings']:
        lines.append('IMPORT '+json.dumps(binding, sort_keys=True, ensure_ascii=False))
    for change in evidence['changes']:
        if change['role'] != 'semantic_expected':
            lines.append(change['id']+' INPUT '+json.dumps(dict(original_span=change['original_span'], modified_span=change['span']), sort_keys=True))
    for call in evidence['calls']:
        lines.append('CALL '+call['id']+' '+call['callee']+' '+json.dumps(call['span'],sort_keys=True))
        for target in call['targets']:
            lines.append('  => '+target['function_id']+' ['+target['reason']+']')
        for mapping in call['actual_formal']:
            actual = mapping['actual'] if len(mapping['actual']) <= 160 else 'expression at '+json.dumps(mapping['actual_span'], sort_keys=True)
            lines.append('  '+actual+' -> '+mapping['parameter'])
    for assertion in evidence['assertions']:
        code = assertion['code'] if len(assertion['code']) <= 240 else 'assertion at '+json.dumps(assertion['span'], sort_keys=True)
        lines.append('Q:'+assertion['id']+' OLD EXPECTATION '+code)
    lines.extend(_render_obligations(evidence.get('original_observation_obligations', [])))
    for edge in evidence['edges']:
        lines.append(json.dumps(edge, sort_keys=True, ensure_ascii=False))
    for callback in evidence.get('function_valued_arguments', []):
        lines.append('FUNCTION ARGUMENT '+json.dumps(callback,sort_keys=True,ensure_ascii=False))
    for control in evidence['controls']:
        lines.append('SOURCE CONTROL '+json.dumps(control, sort_keys=True, ensure_ascii=False))
    rendered_contexts = []
    for context in sorted(evidence['declarations'], key=lambda c:(c['span']['path'],c['span']['start_byte'],-c['span']['end_byte'])):
        owner = next((row for row in rendered_contexts if row['source_sha256']==context['source_sha256']
                      and row['span']['path']==context['span']['path']
                      and row['span']['start_byte']<=context['span']['start_byte']
                      and context['span']['end_byte']<=row['span']['end_byte']),None)
        if owner is not None:
            lines.append('SOURCE INCLUDED IN '+json.dumps(owner['span'],sort_keys=True)+' FOR '+','.join(context['roles']))
            continue
        rendered_contexts.append(context)
        lines.extend(['SOURCE '+json.dumps(dict(span=context['span'], roles=context['roles'],
                                               sha256=context['source_sha256']), sort_keys=True), context['code']])
    for row in evidence['unknowns']:
        lines.append('UNKNOWN '+json.dumps(row, sort_keys=True, ensure_ascii=False))
    return '\n'.join(lines)+'\n'
