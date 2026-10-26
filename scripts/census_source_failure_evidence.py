"""Source-only census of unproved local assertion adapters in a sealed cohort.

The imported callee is resolved from the actual import declaration, explicit Go
module roots and package source. Its spelling never makes it an assertion. The
failure analyser supplies only source facts; no expected value or safe edit is
inferred. This script never reads completions, target labels or execution logs.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, literal, walk
from prototypes.local_helper_evidence import analyze as local_analysis
from prototypes.local_helper_evidence import _function_scope, _receiver_rebound
from generic_composition.corpus import span
from relation_search.oracle_evidence import _modified_sources

VERSION = 'source-failure-cohort-v1'
FILES = ['scripts/census_source_failure_evidence.py',
    'tests/test_source_failure_census.py', 'prototypes/source_failure_evidence.py',
    'tests/test_source_failure_evidence.py',
    'prototypes/local_helper_evidence.py', 'tests/test_local_helper_evidence.py',
    'prototypes/go_assertion_helper.py',
    'prototypes/go_arity_guard.py', 'relation_search/oracle_evidence.py',
    'relation_search/instrument.py', 'anchor_retrieval/syntax.py',
    'anchor_retrieval/index.py', 'anchor_retrieval/graph.py',
    'generic_composition/corpus.py', 'relational_gap/frontend.py']


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + '\n')


def package(source):
    clauses = [n for n in source.root.named_children if n.type == 'package_clause']
    if len(clauses) != 1 or clauses[0].has_error or len(clauses[0].named_children) != 1:
        return None
    return source.text(clauses[0].named_children[0])


def import_path(source, modules):
    """Use the longest declared module root; never infer module/package names."""
    directory = str(PurePosixPath(source.lookup_path).parent)
    directory = '' if directory == '.' else directory
    choices = []
    for raw_root, module in modules.items():
        if not isinstance(raw_root, str) or not isinstance(module, str):
            continue
        root = raw_root.rstrip('/')
        root = '' if root == '.' else root
        if not root or directory == root or directory.startswith(root + '/'):
            relative = directory[len(root):].lstrip('/') if root else directory
            choices.append((len(root), module.rstrip('/') + ('/' + relative if relative else '')))
    if not choices:
        return None
    depth = max(row[0] for row in choices)
    names = {name for length, name in choices if length == depth}
    return next(iter(names)) if len(names) == 1 else None


def source_parameters(source, function):
    result = []
    params = child(function, 'parameters')
    if params is None:
        return None
    for item in params.named_children:
        if item.type == 'comment':
            continue
        if item.type not in {'parameter_declaration', 'variadic_parameter_declaration'}:
            return None
        names = [n for n in item.named_children if n.type == 'identifier']
        if not names:
            return None
        for name in names:
            result.append(dict(name=source.text(name), type=source.text(child(item, 'type')),
                variadic=item.type == 'variadic_parameter_declaration', span=span(source, name)))
    if any(row['variadic'] for row in result[:-1]):
        return None
    return result


def bind_arguments(source, call, target_source, target):
    params = source_parameters(target_source, target)
    if params is None:
        return dict(status='unknown', reason='unsupported_callee_parameters', actual_formal=[])
    _, args = call_parts(call)
    variadic = bool(params and params[-1]['variadic'])
    fixed = len(params) - int(variadic)
    spread = [i for i, arg in enumerate(args) if arg.type == 'variadic_argument']
    if len(args) < fixed or (not variadic and len(args) != fixed):
        return dict(status='unknown', reason='argument_arity_mismatch', actual_formal=[])
    if spread and (not variadic or spread != [len(args) - 1] or len(args) != len(params)):
        return dict(status='unknown', reason='unsupported_variadic_argument_binding', actual_formal=[])
    mappings = []
    for i, parameter in enumerate(params):
        values = args[i:] if parameter['variadic'] else [args[i]]
        mappings.append(dict(index=i, formal=parameter,
            actuals=[dict(code=source.text(arg), span=span(source, arg),
                spread=arg.type == 'variadic_argument') for arg in values]))
    return dict(status='source_bound', reason=None, actual_formal=mappings)


def resolve_imported_call(source, call, sources, module_resolution):
    """Resolve one selector call, including default aliases backed by package clauses."""
    callee, _ = call_parts(call)
    receiver, name = attr_parts(callee) if callee is not None else (None, None)
    if receiver is None or receiver.type != 'identifier' or name is None:
        return dict(status='unknown', reason='callee_not_import_selector')
    receiver_name = source.text(receiver)
    function = _function_scope(call)
    if function is None or _receiver_rebound(source, function, receiver_name):
        return dict(status='unknown', reason='import_receiver_shadowed_or_reassigned')
    modules = module_resolution.get('go_modules') or {}
    candidates = []
    for spec in (n for n in walk(source.root) if n.type == 'import_spec'):
        try:
            module = literal(source.text(child(spec, 'path')))
        except (ValueError, TypeError):
            continue
        alias = source.text(child(spec, 'name'))
        if alias in {'_', '.'}:
            continue
        target_sources = [other for other in sources if other.language == 'go'
            and not other.lookup_path.endswith('_test.go')
            and import_path(other, modules) == module and package(other) is not None]
        packages = {package(other) for other in target_sources}
        if alias:
            bound = alias == receiver_name
        else:
            bound = len(packages) == 1 and receiver_name in packages
        if not bound:
            continue
        if not target_sources:
            candidates.append(dict(status='unknown', reason='import_source_unavailable', module=module))
            continue
        if len(packages) != 1:
            candidates.append(dict(status='unknown', reason='import_source_package_ambiguous', module=module))
            continue
        declarations = [(other, node) for other in target_sources
            if not other.root.has_error for node in other.root.named_children
            if node.type == 'function_declaration' and other.text(child(node, 'name')) == source.text(name)]
        if len(declarations) != 1:
            candidates.append(dict(status='unknown', reason='import_declaration_missing_or_ambiguous',
                module=module, declaration_count=len(declarations)))
            continue
        other, node = declarations[0]
        binding = bind_arguments(source, call, other, node)
        candidates.append(dict(status=binding['status'], reason=binding['reason'], module=module,
            import_span=span(source, spec), import_code=source.text(spec),
            package=package(other), declaration_name=source.text(name), declaration_span=span(other, node),
            declaration_code=other.text(node), declaration_source_sha256=hashlib.sha256(other.data).hexdigest(),
            declaration_sha256=hashlib.sha256(other.text(node).encode()).hexdigest(),
            actual_formal=binding['actual_formal']))
    if len(candidates) != 1:
        return dict(status='unknown', reason='import_binding_missing_or_ambiguous',
            import_candidates=candidates)
    return candidates[0]


def _extent(value):
    return (value['path'], value['start_byte'], value['end_byte'])


def attach_failure_evidence(binding, analysis):
    """Join by exact declaration bytes, not API/helper names."""
    if binding.get('status') != 'source_bound':
        return dict(status='unknown', reason='source_call_not_bound')
    functions = [row for row in analysis.get('functions', [])
        if _extent(row['span']) == _extent(binding['declaration_span'])]
    if len(functions) != 1:
        return dict(status='unknown', reason='failure_analysis_declaration_missing_or_ambiguous')
    function = functions[0]
    if function.get('source_sha256') != binding['declaration_source_sha256']:
        return dict(status='unknown', reason='failure_analysis_source_sha_mismatch')
    ident = function['id']
    functions_by_id = {row['id']: row for row in analysis.get('functions', [])}
    # Preserve the source path to transitive sinks, rather than returning only
    # the entry API's boolean. Unresolved/static-dispatch-unknown calls stay so.
    reachable = {ident}
    while True:
        new = {row.get('target_id') for row in analysis.get('calls', [])
            if row.get('caller_id') in reachable and row.get('target_id') in functions_by_id
            and row.get('status') == 'same_package_static_call'
            and functions_by_id[row['target_id']].get('can_reach_failure', False)}
        if new <= reachable:
            break
        reachable |= new
    check_ids = {check for fid in reachable for check in functions_by_id[fid].get('check_call_ids', [])}
    conditions = [row for row in analysis.get('conditions', [])
        if row.get('check_call_id') in check_ids or row.get('function_id', row.get('owner')) in reachable]
    calls = [row for row in analysis.get('calls', []) if row.get('caller_id') in reachable]
    sinks = [row for row in analysis.get('sinks', [])
        if row.get('id') in check_ids or row.get('function_id', row.get('caller_id')) in reachable]
    sink_call_ids = {row.get('call_id', row.get('id')) for row in sinks}
    # One shortest finite source path per sink, independent of callee spelling.
    queue, paths = deque([(ident, [])]), {ident: []}
    while queue:
        current, path = queue.popleft()
        for row in sorted(calls, key=lambda r: r['id']):
            if row.get('caller_id') != current or row.get('status') != 'same_package_static_call':
                continue
            target = row.get('target_id')
            if target in reachable and target not in paths:
                paths[target] = path + [row]
                queue.append((target, paths[target]))
    failure_paths = []
    for row in sorted(calls, key=lambda r: r['id']):
        if row['id'] in sink_call_ids and row.get('caller_id') in paths:
            failure_paths.append(paths[row['caller_id']] + [row])
    call_ids = {row['id'] for row in calls}
    extents = [functions_by_id[fid]['span'] for fid in reachable]
    source_paths = {extent['path'] for extent in extents}
    relevant_unknowns = []
    for row in analysis.get('unknowns', []):
        extent = row.get('span')
        inside = extent is not None and any(extent['path'] == owner['path']
            and owner['start_byte'] <= extent['start_byte'] <= extent['end_byte'] <= owner['end_byte']
            for owner in extents)
        file_unknown = row.get('reason') == 'source_parse_error' and row.get('path') in source_paths
        if row.get('function_id') in reachable or row.get('call_id') in call_ids or inside or file_unknown:
            relevant_unknowns.append(row)
    return dict(status='source_facts', function=function, conditions=conditions,
        same_package_calls=calls, sink_evidence=sinks,
        shortest_failure_paths=failure_paths,
        failure_checks=[row for row in analysis.get('checks', []) if row.get('id') in check_ids or row.get('call_id') in check_ids],
        reachable_functions=[functions_by_id[fid] for fid in sorted(reachable)],
        can_reach_failure=function.get('can_reach_failure', False),
        unknowns=relevant_unknowns, limits=analysis.get('limits', []),
        interpretation='may reach a source-proved testing failure; no assertion contract or expected role inferred')


def collect_candidate(corpus, candidate, frontend, failure_analysis):
    local = local_analysis(corpus, candidate)
    rows = {}
    for call in local['calls']:
        for assertion in call['assertions']:
            reason = assertion.get('expected_port_reason')
            if reason not in {'assertion_adapter_import_unproved', 'assertion_adapter_rebound'}:
                continue
            key = _extent(assertion['span'])
            row = rows.setdefault(key, dict(span=assertion['span'], code=assertion['code'],
                adapter_unproved_reason=reason, instances=[], expected_port_status='unknown'))
            row['instances'].append(dict(local_helper_call_id=call['id'],
                local_helper_call_span=call['span'], local_helper_actual_formal=call['actual_formal']))
    if corpus['language'] != 'go':
        for row in rows.values():
            row['binding'] = dict(status='unknown', reason='language_not_supported')
            row['failure_evidence'] = dict(status='unknown', reason='language_not_supported')
    else:
        sources, owner, *_ = _modified_sources(corpus, candidate)
        nodes = {(n.start_byte, n.end_byte): n for n in walk(owner.root)}
        for row in rows.values():
            extent = row['span']
            node = nodes.get((extent['start_byte'], extent['end_byte']))
            if node is None or owner.text(node) != row['code']:
                row['binding'] = dict(status='unknown', reason='local_call_source_mismatch')
            else:
                row['binding'] = resolve_imported_call(owner, node, sources, frontend.get('module_resolution', {}))
            row['failure_evidence'] = attach_failure_evidence(row['binding'], failure_analysis)
    return dict(version=VERSION, candidate_id=candidate['id'], language=corpus['language'],
        local_analysis_counts=local.get('counts', {}), calls=list(rows.values()),
        limits=['denominator selected by existing unproved adapter inventory, not all source assertions',
            'source failure reachability never proves a valid oracle or editable expected argument',
            'unknown adapter status is retained; no production oracle edits'])


def audit_candidate_sources(corpus, candidate, result):
    """Independently recover every emitted argument/declaration/failure extent."""
    _, modified, *_ = _modified_sources(corpus, candidate)
    originals = {path: row['code'].encode() for path, row in corpus['sources'].items()}
    current = dict(originals, **{modified.path: modified.data})
    counts = Counter()

    def at(extent, code=None, *, data=current):
        raw = data[extent['path']]
        lower, upper = extent['start_byte'], extent['end_byte']
        if not 0 <= lower <= upper <= len(raw):
            raise ValueError('evidence span outside source')
        actual = raw[lower:upper].decode()
        if code is not None and code != actual:
            raise ValueError('evidence code differs from exact source span')
        counts['verified_extents'] += 1
        return actual

    for call in result['calls']:
        at(call['span'], call['code'])
        binding = call['binding']
        if binding.get('status') != 'source_bound':
            continue
        declaration = at(binding['declaration_span'], binding['declaration_code'])
        if hashlib.sha256(declaration.encode()).hexdigest() != binding['declaration_sha256']:
            raise ValueError('declaration SHA mismatch')
        if hashlib.sha256(current[binding['declaration_span']['path']]).hexdigest() != binding['declaration_source_sha256']:
            raise ValueError('declaration source SHA mismatch')
        at(binding['import_span'], binding['import_code'])
        for row in binding['actual_formal']:
            at(row['formal']['span'], row['formal']['name'])
            for actual in row['actuals']:
                at(actual['span'], actual['code'])
        proof = call['failure_evidence']
        for function in proof.get('reachable_functions', []):
            extent = function['span']
            at(extent, function.get('code'), data=originals)
            if hashlib.sha256(originals[extent['path']]).hexdigest() != function['source_sha256']:
                raise ValueError('failure function source SHA mismatch')
            for formal in function.get('parameters', []):
                at(formal['span'], formal['name'], data=originals)
        for row in proof.get('same_package_calls', []) + proof.get('sink_evidence', []):
            at(row['span'], row['code'], data=originals)
            for mapping in row.get('actual_formal', []):
                at(mapping['formal']['span'], mapping['formal']['name'], data=originals)
                for actual in mapping['actuals']:
                    at(actual['span'], actual['code'], data=originals)
            for actual in row.get('diagnostic_arguments', []):
                at(actual['span'], actual['code'], data=originals)
            if row.get('receiver_formal'):
                formal = row['receiver_formal']
                at(formal['span'], formal['name'], data=originals)
        for condition in proof.get('conditions', []):
            at(condition['branch_span'], data=originals)
            expression = condition.get('expression')
            if isinstance(expression, dict) and expression.get('span'):
                at(expression['span'], expression.get('code'), data=originals)
            for operand in condition.get('operands', []):
                at(operand['span'], operand.get('code'), data=originals)
            for pattern in condition.get('case_patterns', []):
                at(pattern['span'], pattern.get('code'), data=originals)
        canonical_calls = {row['id']: row for row in proof.get('same_package_calls', [])}
        confirmed_sinks = {row['call_id'] for row in proof.get('sink_evidence', [])}
        paths = proof.get('shortest_failure_paths', [])
        if proof.get('can_reach_failure') and not paths:
            raise ValueError('failure reachability has no source path witness')
        for path in paths:
            if not path:
                raise ValueError('empty failure path')
            current_function = proof['function']['id']
            for i, step in enumerate(path):
                if canonical_calls.get(step['id']) != step:
                    raise ValueError('failure path differs from canonical source call')
                if step['caller_id'] != current_function:
                    raise ValueError('failure path caller/target discontinuity')
                if i == len(path)-1:
                    if step['id'] not in confirmed_sinks or step.get('status') != 'testing_sink':
                        raise ValueError('failure path does not end at a confirmed testing sink')
                else:
                    if step.get('status') != 'same_package_static_call':
                        raise ValueError('failure path has an unproved dispatch edge')
                    current_function = step['target_id']
    return dict(status='exact_source_verified', **counts,
        limits='byte identity and provenance only; not path feasibility or an oracle contract')


def run(paired, output):
    from prototypes.source_failure_evidence import analyze_corpus
    protocol, ready = read(paired/'protocol.json'), read(paired/'ready.json')
    if digest(paired/'protocol.json') != ready['protocol_sha256']:
        raise ValueError('paired protocol does not match ready record')
    if len(ready['records']) != 17 or sum(len(r.get('member_ids', [])) for r in ready['records']) != 50:
        raise ValueError('census requires the original sealed 17-case, 50-member cohort')
    inventory = Path(protocol['inventory'])
    inputs = {str((paired/name).resolve()): digest(paired/name) for name in ['protocol.json', 'ready.json']}
    for record in ready['records']:
        if record['status'] != 'offerable':
            continue
        request = Path(record['arms']['template']['request'])
        if digest(request) != record['arms']['template']['request_sha256']:
            raise ValueError('paired source request changed')
        inputs[str(request.resolve())] = digest(request)
        for name in ['corpus.json', 'frontend.json']:
            path = inventory/record['case']/name
            if digest(path) != protocol['input_sha256'][record['case']][name]:
                raise ValueError('paired source inventory changed')
            inputs[str(path.resolve())] = digest(path)
    hashes = {name: digest(ROOT/name) for name in FILES}
    output.mkdir(parents=True, exist_ok=False)
    write(output/'protocol.json', dict(version=VERSION, paired=str(paired.resolve()),
        inputs_sha256=inputs, code_sha256=hashes,
        selection='all 50 already sealed members, 17 cases; no outcome or target selection',
        denominator='unique candidate-specific unproved local-helper adapter call sites plus separately counted local call instances',
        import_rule='actual import spec and unique source package/function under explicit longest Go module root',
        provider_calls=0, subject_executions=0, production_oracle_edits=0,
        forbidden_inputs=['completions', 'target labels', 'native results', 'hidden verifier', 'reference patch']))
    for name in FILES:
        path = output/'code_snapshot'/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT/name).read_bytes())
    summaries, totals, reasons, apis = [], Counter(), Counter(), {}
    for record in ready['records']:
        case, members = record['case'], []
        if record['status'] == 'offerable':
            request = read(record['arms']['template']['request'])
            corpus, frontend = read(inventory/case/'corpus.json'), read(inventory/case/'frontend.json')
            if [r['candidate']['id'] for r in request['offered'].values()] != record['member_ids']:
                raise ValueError('paired member inventory changed')
            analysis = analyze_corpus(corpus) if corpus['language'] == 'go' else {}
            write(output/case/'source_failure_analysis_summary.json',
                {key: analysis.get(key) for key in ['version', 'status', 'counts', 'limits']})
            for alias, offered in request['offered'].items():
                result = collect_candidate(corpus, offered['candidate'], frontend, analysis)
                result['independent_source_audit'] = audit_candidate_sources(corpus, offered['candidate'], result)
                write(output/case/(alias+'.json'), result)
                counts = Counter(members=1, unproved_call_sites=len(result['calls']),
                    unproved_instances=sum(len(c['instances']) for c in result['calls']))
                counts['members_with_unproved_adapter_calls'] = int(bool(result['calls']))
                for call in result['calls']:
                    bound = call['binding']['status'] == 'source_bound'
                    proof = call['failure_evidence']
                    counts['source_bound_calls'] += int(bound)
                    counts['source_failure_reachable_calls'] += int(proof.get('can_reach_failure', False))
                    counts['calls_with_failure_sink_evidence'] += int(bool(proof.get('sink_evidence')))
                    counts['calls_with_control_predicate_evidence'] += int(bool(proof.get('conditions')))
                    counts['calls_with_actual_formal_evidence'] += int(bound and bool(call['binding'].get('actual_formal')))
                    if bound:
                        binding = call['binding']
                        api_key = hashlib.sha256(json.dumps([binding['module'],binding['declaration_source_sha256'],
                            binding['declaration_span']],sort_keys=True).encode()).hexdigest()
                        api = apis.setdefault(api_key,dict(id=api_key,module=binding['module'],
                            declaration_span=binding['declaration_span'],declaration_sha256=binding['declaration_sha256'],
                            declaration_source_sha256=binding['declaration_source_sha256'],
                            can_reach_failure=proof.get('can_reach_failure',False),
                            condition_count=len(proof.get('conditions',[])),sink_count=len(proof.get('sink_evidence',[])),
                            relevant_unknown_count=len(proof.get('unknowns',[])),
                            assertion_contract_status='unknown',member_call_occurrences=[]))
                        api['member_call_occurrences'].append(dict(case=case,alias=alias,
                            candidate_id=offered['candidate']['id'],call_span=call['span']))
                    if not bound:
                        reasons[call['binding']['reason']] += 1
                    elif proof.get('status') != 'source_facts':
                        reasons[proof['reason']] += 1
                counts['members_with_source_failure_evidence'] = int(bool(counts['source_failure_reachable_calls']))
                members.append(dict(alias=alias, candidate_id=offered['candidate']['id'], counts=dict(counts)))
                totals.update(counts)
        summaries.append(dict(case=case, members=members))
        print(json.dumps(dict(case=case, members=len(members),
            unproved_call_sites=sum(r['counts']['unproved_call_sites'] for r in members))), flush=True)
    final = dict(version=VERSION, cases=len(summaries), totals=dict(totals),
        binding_unknown_reasons=dict(reasons), cases_detail=summaries,
        source_apis=[apis[key] for key in sorted(apis)],
        interpretation='source support only: no adapter promotion, oracle correctness, safe port edit or detection benefit')
    write(output/'summary.json', final)
    if any(digest(Path(path)) != expected for path, expected in inputs.items()) or hashes != {name:digest(ROOT/name) for name in FILES}:
        raise ValueError('input or code changed during census; no seal')
    write(output/'seal.json', dict(files_sha256={str(path.relative_to(output)):digest(path)
        for path in sorted(output.rglob('*')) if path.is_file()}))
    return final


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--paired', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.paired, args.output)['totals']))
