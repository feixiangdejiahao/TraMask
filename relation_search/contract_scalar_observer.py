"""Source-bound scalar observations across existing TypeScript boundaries.

The model selects a receiver, method and existing argument expressions. It
cannot supply code, change an action or replace an original assertion. Static
binding checks deliberately do not certify purity or observation equivalence.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import re
import sys

from anchor_retrieval.syntax import Source, call_parts, child, walk
from relation_search import contract_observation_boundary as boundary
from relation_search import contract_gap_proposals as context
from relation_search import compact_admission, oracle, source_contract_evidence

VERSION = 'source-contract-scalar-observer.v1'
MAX_HOSTS = 16
MAX_PROPOSALS = 3
MAX_ARGUMENTS = 3
MAX_DONORS = 32
MAX_PROMPT_BYTES = 96000
POLICY = dict(version=VERSION, language='typescript', max_hosts=MAX_HOSTS,
    purpose='Observe a contract-defined scalar projection across an existing boundary, using existing inputs and objects.',
    hosts='Original synchronous complete tests; direct zero-argument method statement; test-local const owner from an imported zero-argument factory. Fixed retrieval_rank/path/boundary-byte order.',
    model='Select one source host, one bound receiver, an identifier method, zero to three source argument donors, scalar type and exact public-issue quote. No free code or action/oracle changes.',
    donors='First 32 unique primitive/const/import/simple bound-call argument expressions from preceding non-assertion statements of this full test. Simple calls have a bound identifier callee and primitive or const/import arguments.',
    capture='Immediately before the original boundary, evaluate each selected argument once into a fresh const, then evaluate Q. Immediately after that boundary, evaluate the same Q with the same captured arguments and compare. Original argument evaluations and all original statements remain untouched.',
    binding='Resolve exact lexical definitions at original donor and capture points. Object identity, library aliasing, callable purity and value stability remain explicit semantic obligations.',
    scalar='The independent gate must prove a stable boolean, number or string domain. No deep equality, live snapshots or coercion.',
    admission='Fresh complete-test review must establish observer/argument purity, definedness in both phases, public preservation contract, capture timing and every retained assertion. Generation quotes are hypotheses, not review authority.',
    limits=['TypeScript only; no async, callbacks, receiver aliases/escapes, new imports, field projections, arbitrary expressions or new subject actions.',
            'A const binding does not prove immutable contents. A source call donor does not prove a pure call.',
            'A passing source control does not establish original oracle validity.',
            'This development experiment does not establish new detection capability or cross-task generalization.'],
    forbidden_inputs=['old candidates', 'native outcomes', 'audit labels', 'hidden/reference tests'])
SYSTEM = '''Select up to three contract-supported scalar observations for the supplied original tests.
Return only {"observations":[{"host_alias":"H1","receiver_alias":"R1","method":"methodName","argument_aliases":["A1"],"scalar_kind":"boolean","issue_quote":"exact unique quote from public issue"}]}.
You may select only listed hosts, receivers and argument donors. The method is one plain identifier, not code. Return an empty list when evidence is missing.
The fixed constructor evaluates each argument donor ONCE into a new const immediately before the existing boundary, then reads Q before and after that boundary and compares the scalar results. It retains every original operation and assertion, including the original donor evaluations. You cannot change inputs or actions.
Require a public contract that preserves this exact observation across this boundary and covers the actual receiver relationship. Method-name similarity is insufficient. Require both Q reads and the EXTRA argument evaluations to be defined, repeatable and free of side effects. A const binding does not establish immutable contents. Both reads must return the specified primitive scalar type. Check destroyed objects, pending operations, callbacks, capture timing, aliases, exceptions and all later assertions. Do not infer an oracle from current implementation behavior. Source controls are examples, not proof.
Your quote is a proposal receipt only. A separate fresh full-test reviewer will make admission decisions without your reasoning. Do not output reasoning, patches or rewritten tests.'''


def _hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _binding_record(source, binding):
    if binding['kind'] == 'import':
        return dict(kind='import', canonical=binding['canonical'])
    return dict(kind='const', definition=boundary.receipt(source.path, source.code,
        binding['node'].start_byte, binding['node'].end_byte))


def _argument(source, node, entry, *, nested=False):
    """Bind a narrow donor expression; no purity inference is made here."""
    if node.type in {'true', 'false', 'number', 'string', 'null'}:
        return []
    if node.type == 'identifier':
        old = boundary._resolve(source, source.text(node), node)
        new = boundary._resolve(source, source.text(node), entry)
        if old['key'] != new['key']:
            raise ValueError('argument_binding_changes_at_capture')
        return [_binding_record(source, old)]
    if node.type == 'call_expression' and not nested:
        fn, args = call_parts(node)
        if fn.type != 'identifier' or len(args) > MAX_ARGUMENTS:
            raise ValueError('argument_call_shape_unsupported')
        bound = _argument(source, fn, entry, nested=True)
        for arg in args:
            bound.extend(_argument(source, arg, entry, nested=True))
        return bound
    raise ValueError('argument_expression_unsupported')


def _assertion_statement(source, statement):
    for node in walk(statement):
        if node.type != 'call_expression':
            continue
        fn, _ = call_parts(node)
        if fn.type != 'identifier':
            continue
        try:
            binding = boundary._resolve(source, source.text(fn), fn)
        except ValueError:
            continue
        if (binding['kind'] == 'import' and binding['canonical'][0] in {'vitest', '@jest/globals'}
                and binding['canonical'][1] in {'expect', 'assert'}):
            return True
    return False


def catalog(corpus, frontend):
    result = dict(version=VERSION, status='language_unsupported', hosts=[], rejected=[],
                  repository_tests=0, host_count=0, selected_host_count=0)
    if corpus['language'] != 'typescript':
        return result
    files = {}
    for identifier, test in sorted(corpus['tests'].items(), key=context._order):
        path = test['span']['path']; row = corpus['sources'][path]
        if row.get('origin') != 'repository':
            continue
        result['repository_tests'] += 1
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:' + path)
        try:
            if path not in files:
                files[path] = Source(path, row['code'], 'typescript')
            source = files[path]
            context._source_test(corpus, identifier)
            root, statements = boundary._callback(source, test['span'])
        except ValueError as exc:
            result['rejected'].append(dict(base_test_id=identifier, reason=str(exc))); continue
        for position, statement in enumerate(statements):
            try:
                call, chain = boundary._call_statement(source, statement)
                owner = boundary._resolve(source, chain[0], statement)
                if owner['kind'] != 'const' or owner['node'].parent.parent != child(root, 'body'):
                    raise ValueError('owner_not_test_local_const')
                init = owner['value']
                if init is None or init.type != 'call_expression':
                    raise ValueError('owner_not_direct_factory_call')
                fn, args = call_parts(init)
                if fn.type != 'identifier' or args:
                    raise ValueError('owner_factory_not_zeroarg_identifier')
                factory = boundary._resolve(source, source.text(fn), fn)
                if factory['kind'] != 'import':
                    raise ValueError('owner_factory_not_imported')
                boundary._check_uses(source, root, [owner], owner)
                expect_names = []
                for name, (module, imported) in source.imports.items():
                    if module not in {'vitest', '@jest/globals'} or imported != 'expect':
                        continue
                    resolved = boundary._resolve(source, name, statement)
                    if resolved['kind'] == 'import' and resolved['canonical'] == [module, imported]:
                        expect_names.append(name)
                if len(expect_names) != 1:
                    raise ValueError('expect_import_not_resolved')
            except ValueError as exc:
                result['rejected'].append(dict(base_test_id=identifier, reason=str(exc))); continue
            receivers = []
            for declaration in boundary._scope_declarations(child(root, 'body')):
                if declaration.start_byte >= statement.start_byte:
                    continue
                try:
                    binding = boundary._resolve(source, source.text(child(declaration, 'name')), statement)
                    if binding['kind'] != 'const':
                        continue
                    origin = 'same_binding'
                    if binding['key'] != owner['key']:
                        value = binding['value']
                        if value is None or value.type != 'call_expression':
                            continue
                        creator, _ = call_parts(value); parts = boundary._chain(source, creator)
                        if len(parts) < 2 or boundary._resolve(source, parts[0], value)['key'] != owner['key']:
                            continue
                        origin = 'created_by_owner'
                    boundary._check_uses(source, root, [owner, binding], owner)
                    receivers.append(dict(alias='R'+str(len(receivers)+1), name=binding['name'],
                        origin=origin, **_binding_record(source, binding)))
                except ValueError:
                    continue
            donors = []; seen = set()
            for prior in statements[:position]:
                if _assertion_statement(source, prior):
                    continue
                for node in walk(prior):
                    if node.parent is None or node.parent.type != 'arguments':
                        continue
                    try:
                        bindings = _argument(source, node, statement)
                    except ValueError:
                        continue
                    key = (source.text(node), json.dumps(bindings, sort_keys=True))
                    if key in seen:
                        continue
                    seen.add(key)
                    donors.append(dict(alias='A'+str(len(donors)+1), expression=boundary.receipt(
                        path, source.code, node.start_byte, node.end_byte), bindings=bindings,
                        purity='unknown_requires_fresh_full_test_review'))
            result['hosts'].append(dict(host_alias='H'+str(len(result['hosts'])+1),
                base_test_id=identifier, order=[*context._order((identifier, test)), statement.start_byte],
                boundary=boundary.receipt(path, source.code, call.start_byte, call.end_byte),
                boundary_statement=boundary._span(source, statement),
                expect_callee=expect_names[0],
                owner_factory=factory['canonical'], owner=_binding_record(source, owner),
                receivers=receivers, argument_donors=donors[:MAX_DONORS],
                omitted_argument_donors=max(0, len(donors)-MAX_DONORS), test_span=test['span']))
    result.update(status='source_hosts', host_count=len(result['hosts']),
        selected_host_count=min(MAX_HOSTS, len(result['hosts'])))
    return result


def seed_ids(corpus, frontend):
    return list(dict.fromkeys(h['base_test_id'] for h in catalog(corpus, frontend)['hosts'][:MAX_HOSTS]))


def prepare(corpus, frontend, issue, *, max_prompt_bytes=MAX_PROMPT_BYTES, max_output_tokens=16384):
    if not 1 <= max_prompt_bytes <= MAX_PROMPT_BYTES:
        raise ValueError('unsupported_prompt_budget')
    hosts = catalog(corpus, frontend)
    selected = hosts['hosts'][:MAX_HOSTS]
    api = context.issue_api_catalog(corpus, issue)
    payload = dict(version=VERSION, issue=oracle.issue_contract(issue, max_chars=None),
        policy=POLICY, issue_api_catalog=api, seeds=[], hosts=[])
    seeds, omitted = [], []
    for identifier in dict.fromkeys(h['base_test_id'] for h in selected):
        source, test, _ = context._source_test(corpus, identifier)
        identity = dict(id=identifier, base_test_id=identifier, source_test_ids=[identifier], edits=[], imports=[])
        result = compact_admission.prepare(corpus, frontend, identity, issue,
            max_prompt_bytes=sys.maxsize, max_output_tokens=max_output_tokens)
        attached = [h for h in selected if h['base_test_id'] == identifier]
        if result.get('request') is None:
            omitted.append(dict(base_test_id=identifier, hosts=[h['host_alias'] for h in attached], reason=result['status'])); continue
        content = json.loads(result['request']['prompt'])
        content['api_contract_context'] = source_contract_evidence.collect(corpus,
            result['analysis'], max_bytes=sys.maxsize, max_types=sys.maxsize)
        entry = dict(base_test_id=identifier, context=content)
        proposed = dict(payload, seeds=[*payload['seeds'], entry], hosts=[*payload['hosts'], *attached])
        size = len(SYSTEM.encode())+len(json.dumps(proposed, ensure_ascii=False, separators=(',', ':')).encode())
        if size > max_prompt_bytes:
            omitted.append(dict(base_test_id=identifier, hosts=[h['host_alias'] for h in attached],
                reason='whole_context_prompt_budget', required_bytes=size)); continue
        payload = proposed
        seeds.append(dict(base_test_id=identifier, span=test['span'], body_span=test['body_span'],
            source_sha256=_hash(source.code), context_sha256=context.digest(content),
            original_test_sha256=_hash(content['original_test']), context_status=result['analysis']['status'],
            context_coverage=result.get('coverage', {})))
    hashes = {p:_hash(r['code']) for p,r in sorted(corpus['sources'].items()) if r.get('origin')=='repository'}
    result = dict(version=VERSION, policy=POLICY, catalog=hosts, seeds=seeds, omitted=omitted,
        source_sha256=hashes, request=None, external_model_calls=0, native_executions=0,
        truncated=False, alarm_eligible=False)
    if not seeds:
        return dict(result, status='language_unsupported' if corpus['language']!='typescript' else 'no_complete_host_context')
    prompt = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    request = dict(system=SYSTEM, prompt=prompt, kind=VERSION, max_tokens=max_output_tokens,
        thinking='enabled', reasoning_effort='high', prompt_bytes=len(SYSTEM.encode())+len(prompt.encode()),
        source_sha256=hashes, no_execution_outcomes=True, no_evaluation_labels=True,
        external_roles=['public issue', 'complete original tests', 'source-bound hosts/objects/argument expressions', 'public source declarations and helper context'])
    request['id'] = request['query_sha256'] = context._identity(request)
    return dict(result, status='prepared', request=request, prompt_bytes=request['prompt_bytes'])


def _construct(corpus, seed, host, proposal):
    source, test, _ = context._source_test(corpus, seed['base_test_id'])
    receiver = next((r for r in host['receivers'] if r['alias']==proposal['receiver_alias']), None)
    if receiver is None:
        raise ValueError('unknown_receiver_alias')
    donors = {r['alias']:r for r in host['argument_donors']}
    if any(a not in donors for a in proposal['argument_aliases']):
        raise ValueError('unknown_argument_alias')
    chosen = [donors[a] for a in proposal['argument_aliases']]
    semantics = [host['host_alias'], proposal['receiver_alias'], proposal['method'], proposal['argument_aliases']]
    token = context.digest([host, semantics])[:12]
    prefix = '_contractObservation_'+token
    if re.search(r'\b'+prefix+r'\w*\b', source.code):
        raise ValueError('fresh_binding_collision')
    s = host['boundary_statement']; before = source.data[s['start_byte']:s['end_byte']].decode()
    line_prefix = source.data[:s['start_byte']].decode().rsplit('\n',1)[-1]
    indent = line_prefix if not line_prefix.strip() else '    '
    captures = [f'const {prefix}_arg{i} = {d["expression"]["text"]};' for i,d in enumerate(chosen)]
    args = ', '.join(f'{prefix}_arg{i}' for i in range(len(chosen)))
    q = f'{receiver["name"]}.{proposal["method"]}({args})'
    inserted = captures+[f'const {prefix}_before = {q};', before,
        f'const {prefix}_after = {q};', f'{host["expect_callee"]}({prefix}_after).toBe({prefix}_before);']
    replacement = ('\n'+indent).join(inserted)
    full = test['span']; original = source.data[full['start_byte']:full['end_byte']].decode()
    modified = (source.data[full['start_byte']:s['start_byte']]+replacement.encode()+
                source.data[s['end_byte']:full['end_byte']]).decode()
    candidate = context._rewrite(corpus, seed, modified)
    candidate.update(id='scalar_observer_'+context.digest([VERSION,host,proposal])[:24],
        generator=VERSION, kind='contract_scalar_observation_hypothesis',
        source_provenance=dict(version=VERSION, seed=seed['base_test_id'],
            source_file=dict(path=source.path, source_sha256=_hash(source.code), origin='repository'),
            original_test=dict(span=full, utf8_sha256=_hash(original)),
            original_body=dict(span=test['body_span'], utf8_sha256=_hash(candidate['edits'][0]['before'])),
            modified_test_utf8_sha256=_hash(modified)),
        observation_hypothesis=dict(host=host, proposal=proposal,
            argument_extra_evaluations='one per selected donor immediately before old boundary',
            semantic_conditions_proved=False, original_statements_preserved=True))
    return candidate


def decide(corpus, frontend, prepared, response, *, finish_reason='stop'):
    result = dict(version=VERSION, candidates=[], rejected=[], alarm_eligible=False,
                  semantic_validity='unconfirmed', external_model_calls=0, native_executions=0)
    request = prepared.get('request')
    if prepared.get('version')!=VERSION or request is None:
        return dict(result, status='unknown', reason='generation_not_prepared')
    if request['id'] != context._identity(request):
        raise ValueError('generation_request_identity_changed')
    hashes = {p:_hash(r['code']) for p,r in sorted(corpus['sources'].items()) if r.get('origin')=='repository'}
    if hashes != prepared['source_sha256'] or hashes != request['source_sha256']:
        raise ValueError('generation_source_snapshot_changed')
    if finish_reason != 'stop':
        return dict(result, status='unknown', reason='incomplete_provider_response')
    payload = json.loads(request['prompt'])
    recomputed = catalog(corpus, frontend)
    if recomputed != prepared['catalog']:
        raise ValueError('host_source_bindings_changed')
    available = {h['host_alias']:h for h in recomputed['hosts'][:MAX_HOSTS]}
    shown = {h['host_alias']:h for h in payload['hosts']}
    if any(available.get(alias)!=host for alias,host in shown.items()):
        raise ValueError('shown_host_inventory_changed')
    seeds = {s['base_test_id']:s for s in prepared['seeds']}
    if set(seeds) != {s['base_test_id'] for s in payload['seeds']}:
        raise ValueError('shown_seed_inventory_changed')
    for entry in payload['seeds']:
        seed = seeds[entry['base_test_id']]
        if context.digest(entry['context']) != seed['context_sha256']:
            raise ValueError('seed_context_changed')
    try:
        if not isinstance(response,str) or len(response.encode())>262144:
            raise ValueError('response_byte_limit')
        value = json.loads(response, object_pairs_hook=context._unique_object)
        if not isinstance(value,dict) or set(value)!={'observations'} or not isinstance(value['observations'],list) or len(value['observations'])>MAX_PROPOSALS:
            raise ValueError('response_schema')
    except (ValueError,TypeError) as exc:
        return dict(result, status='unknown', reason=str(exc))
    seen=set()
    for rank,proposal in enumerate(value['observations'],1):
        try:
            fields={'host_alias','receiver_alias','method','argument_aliases','scalar_kind','issue_quote'}
            if not isinstance(proposal,dict) or set(proposal)!=fields:
                raise ValueError('proposal_schema')
            if not all(isinstance(proposal[k],str) for k in fields-{'argument_aliases'}):
                raise ValueError('proposal_string_fields')
            if not re.fullmatch(r'[A-Za-z_$][\w$]*',proposal['method'],re.ASCII) or proposal['method'] in {'__proto__','constructor','prototype'}:
                raise ValueError('method_not_plain_identifier')
            if proposal['scalar_kind'] not in {'boolean','number','string'}:
                raise ValueError('nonprimitive_observation')
            args=proposal['argument_aliases']
            if not isinstance(args,list) or len(args)>MAX_ARGUMENTS or not all(isinstance(a,str) for a in args):
                raise ValueError('argument_schema')
            quote=proposal['issue_quote']
            if len(quote)<12 or payload['issue'].count(quote)!=1:
                raise ValueError('issue_quote_not_exact_unique')
            host=shown.get(proposal['host_alias'])
            if host is None or host['base_test_id'] not in seeds:
                raise ValueError('unknown_or_omitted_host')
            candidate=_construct(corpus,seeds[host['base_test_id']],host,proposal)
            # Quotes and scalar labels cannot create duplicate executable programs.
            key=context.digest(candidate['edits'])
            if key in seen:
                raise ValueError('duplicate_observation')
            seen.add(key);candidate['order']=[rank];result['candidates'].append(candidate)
        except (ValueError,KeyError,TypeError,UnicodeError) as exc:
            result['rejected'].append(dict(response_index=rank,status='structurally_rejected',reason=str(exc)))
    return dict(result,status='decoded',proposed=len(value['observations']))
