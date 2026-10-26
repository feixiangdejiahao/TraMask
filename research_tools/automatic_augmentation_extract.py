"""Automatic, source-selected test cohorts with optional trajectory evidence.

This module reads code. It never imports or executes repository code. It does
not infer a missing requirement from a missing assertion. Its outputs are
questions for a subsequent contract review, not proved defects or oracles.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import posixpath
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anchor_retrieval.syntax import (CALLS, Source, call_parts, child, diff_lines,
                                     is_test_path, units, walk)
from relational_gap.history import recover_history

VERSION = 'automatic-augmentation-extraction.v1'
POLICY = {
    'selection': 'All original-corpus repository tests that overlap changed lines, reach a changed declaration through resolved frontend edges, or contain a call whose unbound leaf name matches a changed declaration. No top-k.',
    'order': 'Source path, test start byte, stable original test ID. Name-only links remain weak. No history or outcome affects selection.',
    'history': 'Associate public messages and literal tool commands by relevant paths or identifier tokens. Preserve complete selected public step fields and recoverable source versions. Do not use reasoning_content, final_metrics, labels or generated outcomes.',
    'source_control': 'Identical selected tests and source facts in both arms. History arm only adds trajectory_evidence.',
    'meaning': 'Static call/observation and assignment-channel facts identify questions. They do not prove execution, assertion adequacy, return semantics, alias identity or public contract support.',
    'bounds': 'Original corpus test IDs only. Enumerate other source tests as an unmapped inventory, not runnable candidates. Existing frontend production graph is bounded; unresolved edges remain explicit.',
    'context': 'Complete host files and changed source-test files, plus deduplicated complete related/changed source declarations. Imports come from parsed original source; prompt includes related-file bindings and the same resolved module exports. No source truncation.',
    'history_relevance': 'Test-file path or changed declaration/test-name token in public message/command. Other production-file-only mentions do not establish the tested operation and stay outside the prompt. Raw observations never select evidence.',
    'batching': 'Stable source-order batches contain at most 80 seeds and target at most 2500000 UTF-8 JSON bytes. This is a transport bound, not a model-token count. Before any provider call, local official V4 tokenizer estimates for complete history cases were 128127..940499 tokens; the documented model context is 1M tokens. Keep complete evidence and explicitly mark any single-seed byte overflow.',
}
IDENT = re.compile(r'[A-Za-z_$][\w$]*')
PATH = re.compile(r'[A-Za-z0-9_./-]+\.(?:py|go|tsx?)(?![\w.])')
RUN = re.compile(r'\b(?:pytest|unittest|go\s+(?:test|run)|(?:npx\s+)?(?:tsx|ts-node)|node|vitest|jest|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|python[0-9.]*)\b')
EDIT = re.compile(r'write_(?:text|bytes)\s*\(|\.write\s*\(|\b(?:apply_patch|sed\s+-i|perl\s+-[a-z]*i)\b|\bcat\b[^\n]*>{1,2}|\*\*\*\s+(?:Update|Add|Delete) File:')
READ = re.compile(r'\b(?:cat|sed|head|tail|rg|grep|less|more)\b|read_(?:text|bytes)\s*\(')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def receipt(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def _span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row + 1, end_line=node.end_point.row + 1)


def _at(sources, span):
    source = sources[span['path']]
    return source.data[span['start_byte']:span['end_byte']].decode()


def _targets(call, known):
    return [x['function_id'] for x in call.get('targets', [])
            if x.get('resolved') and x.get('function_id') in known]


def _closure(starts, edges):
    reached, pending = set(), list(starts)
    while pending:
        item = pending.pop()
        if item in reached:
            continue
        reached.add(item)
        pending.extend(edges.get(item, ()))
    return reached


def _public_step(step):
    # A raw receipt points to the full original step. The model sees public
    # messages/tool records only, with no private reasoning or evaluation data.
    return {key: step[key] for key in ('step_id', 'timestamp', 'source', 'message',
                                      'tool_calls', 'observation') if key in step}


def _commands(step):
    for number, call in enumerate(step.get('tool_calls', [])):
        args = call.get('arguments', {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                continue
        if not isinstance(args, dict):
            continue
        command = args.get('command', args.get('cmd'))
        if isinstance(command, str):
            yield number, call.get('function_name'), command


def _path_match(spelling, path):
    spelling, path = spelling.removeprefix('./'), path.removeprefix('./')
    return spelling == path or spelling.endswith('/' + path)


def _channel_facts(source, test, calls, observations):
    """Expose syntactic result channels without declaring them unobserved.

    A tuple slot linked to any use/observation is distinct from the frontend's
    whole-call link. Shadowing, aliases, callbacks and control flow are not
    silently treated as precise data flow.
    """
    facts = []
    root = source.root.named_descendant_for_byte_range(test['span']['start_byte'], test['span']['end_byte'] - 1)
    identifiers = [n for n in walk(root) if n.type == 'identifier']
    for call in calls:
        sp = call['span']
        node = source.root.named_descendant_for_byte_range(sp['start_byte'], max(sp['start_byte'], sp['end_byte'] - 1))
        parent = node.parent
        while parent is not None and parent.start_byte >= test['span']['start_byte'] and parent.type in {'await', 'await_expression', 'parenthesized_expression', 'expression_list'}:
            node, parent = parent, parent.parent
        assignment = parent if parent is not None and parent.type in {'assignment', 'assignment_statement', 'short_var_declaration', 'variable_declarator', 'let_declaration'} else None
        if assignment is None:
            if parent is not None and parent.type == 'expression_statement' and parent.start_byte == node.start_byte:
                facts.append(dict(kind='direct_call_result_not_bound', call_id=call['id'], span=sp,
                                  meaning='The call may intentionally validate an effect or exception.'))
            continue
        lhs = child(assignment, 'left', 'name')
        rhs = child(assignment, 'right', 'value')
        if lhs is None or rhs is None:
            continue
        targets = list(lhs.named_children) if lhs.type in {'pattern_list', 'tuple_pattern', 'list_pattern', 'expression_list', 'array_pattern'} else [lhs]
        slots = []
        for index, target in enumerate(targets):
            name = source.text(target)
            if target.type != 'identifier':
                slots.append(dict(index=index, target=name, status='non_simple_target_unknown'))
                continue
            # Lexical matching is deliberate. It cannot prove def-use identity.
            uses = [n for n in identifiers if source.text(n) == name
                    and assignment.end_byte <= n.start_byte < test['span']['end_byte']]
            linked = [o['id'] for o in observations if o.get('kind') == 'assertion'
                      and o['span']['start_byte'] >= assignment.end_byte
                      and name in IDENT.findall(_at({source.path: source}, o['span']))]
            slots.append(dict(index=index, target=name, discard=(source.language == 'go' and name == '_'),
                              later_identifier_use_spans=[_span(source, n) for n in uses],
                              assertion_identifier_mentions=linked,
                              status='lexical_only_alias_shadow_control_flow_unknown'))
        facts.append(dict(kind='assigned_call_channels', call_id=call['id'], assignment_span=_span(source, assignment),
                          channels=slots, slot_semantics='syntax_only_return_arity_and_projection_not_proved'))
    return facts


def _context_summary(contexts):
    return [{k: c[k] for k in ('kind', 'branch', 'span') if k in c} for c in contexts]


def _binding_summary(binding):
    if not isinstance(binding, dict):
        return binding
    return {k: binding[k] for k in ('id', 'binding_id', 'name', 'status', 'identity_status',
                                  'definition_span', 'span', 'projection_known') if k in binding}


def _import_key(row, language):
    module, path = row['module'], row['source_path']
    if module.startswith('.'):
        if language == 'python':
            dots = len(module) - len(module.lstrip('.'))
            base = posixpath.dirname(path)
            for _ in range(dots - 1):
                base = posixpath.dirname(base)
            return posixpath.normpath(posixpath.join(base, module[dots:].replace('.', '/')))
        return posixpath.normpath(posixpath.join(posixpath.dirname(path), module))
    return module


def _prompt_imports(imports, paths, language):
    modules = {_import_key(i, language) for i in imports if i['source_path'] in paths}
    # Same-module donor bindings permit new operations, without a manually
    # selected API list. Preserve an exact original donor for each binding.
    found = {}
    for row in imports:
        key = _import_key(row, language)
        if row['source_path'] in paths or key in modules:
            found.setdefault((key, row['name'], row['imported_name']),
                             {k: row[k] for k in ('name', 'module', 'imported_name', 'source_path')})
    return list(found.values())


def _history(trajectory, language, candidates, related_paths, related_names):
    steps, events, associations = [], [], []
    for ordinal, original in enumerate(trajectory.get('steps', [])):
        public = _public_step(original)
        commands = list(_commands(public))
        text = str(public.get('message', '')) + '\n' + '\n'.join(x[2] for x in commands)
        tokens = set(IDENT.findall(text))
        paths = set(PATH.findall(text))
        hit_paths = sorted(p for p in related_paths if any(_path_match(x, p) for x in paths))
        hit_names = sorted(name for name in related_names if len(name) >= 3 and name in tokens)
        if not hit_paths and not hit_names:
            continue
        eid = 'step_' + digest([ordinal, public])[:24]
        steps.append(dict(evidence_id=eid, ordinal=ordinal, original_step_sha256=digest(original),
                          public_step_sha256=digest(public), public_step=public))
        associations.append(dict(evidence_id=eid, matched_paths=hit_paths, matched_identifier_tokens=hit_names,
                                 status='literal_source_association_not_runtime_binding'))
        for ci, function, command in commands:
            events.append(dict(evidence_id=eid, ordinal=ordinal, call_index=ci, function_name=function,
                               command_sha256=hashlib.sha256(command.encode()).hexdigest(),
                               command_location='public_step.tool_calls[call_index].arguments.command_or_cmd',
                               run_token=bool(RUN.search(command)),
                               read_token=bool(READ.search(command)), edit_token=bool(EDIT.search(command)),
                               literal_paths=sorted(set(PATH.findall(command))),
                               status='command_syntax_only_no_cwd_shell_effect_or_execution_proof'))
    # Maxima avoid an arbitrary pilot evidence cap. The existing recovery
    # algorithm still documents unsupported edits and content-version dedup.
    safe = {'steps': [_public_step(s) for s in trajectory.get('steps', [])]}
    recovered, recovery = recover_history(safe, language, max_bytes=sys.maxsize, max_versions=sys.maxsize)
    versions = []
    for source in recovered:
        tokens = set(IDENT.findall(source.code))
        path_hit = [p for p in related_paths if source.written_path and _path_match(source.written_path, p)]
        name_hit = sorted(x for x in related_names if len(x) >= 3 and x in tokens)
        if path_hit or name_hit:
            versions.append(dict(evidence_id='version_' + digest([source.path, source.code])[:24],
                                 path=source.path, written_path=source.written_path, step_id=source.step,
                                 text=source.code, sha256=hashlib.sha256(source.data).hexdigest(),
                                 matched_paths=path_hit, matched_identifier_tokens=name_hit,
                                 status='recovered_literal_version_not_verified_executed_on_final_source'))
    by_id = {x['evidence_id']: x for x in associations}
    per_seed = []
    for candidate in candidates:
        names = set(candidate['history_link_identifiers'])
        paths = set(candidate['history_link_paths'])
        ids = [s['evidence_id'] for s in steps if paths.intersection(by_id[s['evidence_id']]['matched_paths'])
               or names.intersection(by_id[s['evidence_id']]['matched_identifier_tokens'])]
        per_seed.append(dict(seed_alias=candidate['seed_alias'], step_evidence_ids=ids,
                             status='lexical_association_requires_semantic_review'))
    return dict(steps=steps, events=events, associations=associations, seed_associations=per_seed,
                recovered_source_versions=versions, recovery_report=recovery,
                unknowns=['No runtime happens-before, final-version coverage, absence-of-execution, heap identity or oracle correctness is inferred.',
                          'Recovery cannot replay arbitrary edits. Equal-content versions may be deduplicated; recurrence is not reconstructed.',
                          'Identifier-only associations can join unrelated methods or public messages. Complete raw observations may include errors; they do not rank tests.'])


def _batches(source_payload, history, candidates, imports, language, *, max_seeds=80, max_bytes=2500000):
    """Stable contiguous partition; no refill, candidate drop or source cuts."""
    public = {c['seed_alias']: c for c in source_payload['seeds']}
    step_links = {c['seed_alias']: c['step_evidence_ids'] for c in history['seed_associations']}

    def package(rows):
        aliases = {c['seed_alias'] for c in rows}
        paths = {c['path'] for c in rows}
        names = {n for c in rows for n in c['history_link_identifiers']}
        step_ids = {eid for alias in aliases for eid in step_links[alias]}
        files = [f for f in source_payload['original_source_files']
                 if f['path'] in paths or f['role'] == 'complete_changed_source_test_file']
        source = {**source_payload, 'seeds': [public[c['seed_alias']] for c in rows], 'original_source_files': files}
        source['permitted_import_bindings'] = _prompt_imports(imports,
            {f['path'] for f in files} | {d['span']['path'] for d in source['related_source_declarations']}, language)
        hs = {**history, 'steps': [x for x in history['steps'] if x['evidence_id'] in step_ids],
              'events': [x for x in history['events'] if x['evidence_id'] in step_ids],
              'associations': [x for x in history['associations'] if x['evidence_id'] in step_ids],
              'seed_associations': [x for x in history['seed_associations'] if x['seed_alias'] in aliases],
              'recovered_source_versions': [x for x in history['recovered_source_versions']
                 if paths.intersection(x['matched_paths']) or names.intersection(x['matched_identifier_tokens'])]}
        augmented = {**source, 'trajectory_evidence': hs}
        return dict(candidates=source['seeds'], source_payload=source, history_payload=augmented,
                    source_bytes=len(encoded(source)), history_bytes=len(encoded(augmented)))

    batches = []
    def add(rows):
        batch = package(rows)
        if len(rows) > 1 and batch['history_bytes'] > max_bytes:
            middle = len(rows) // 2
            add(rows[:middle]); add(rows[middle:])
        else:
            batch['batch_id'] = 'B%02d' % (len(batches) + 1)
            batch['budget_status'] = 'within_bound' if batch['history_bytes'] <= max_bytes else 'single_seed_overflow_no_truncation'
            batches.append(batch)
    for start in range(0, len(candidates), max_seeds):
        add(candidates[start:start + max_seeds])
    return batches


def extract(corpus, frontend, issue, trajectory, patch, *, case=''):
    sources = {p: Source(p, row['code'], row.get('language', corpus['language']), 'repository')
               for p, row in sorted(corpus['sources'].items()) if row.get('origin') == 'repository'}
    for path, source in sources.items():
        if frontend.get('sources', {}).get(path, {}).get('code') != source.code:
            raise ValueError('frontend_source_mismatch:' + path)
    tests = {k: v for k, v in corpus['tests'].items() if v['span']['path'] in sources}
    functions = {f['id']: f for f in frontend.get('functions', []) if f['span']['path'] in sources}
    changed = diff_lines(patch)
    all_units = {}
    for source in sources.values():
        for unit in units(source)[0]:
            all_units[unit.id] = unit
    changed_units = {uid for uid, unit in all_units.items() if not unit.test and not is_test_path(unit.source.path)
                     and any(unit.node.start_point.row + 1 <= line <= unit.node.end_point.row + 1
                             for line in changed.get(unit.source.path, set()))}
    changed_functions = {fid for fid, f in functions.items() if f.get('production') and
                         any(f['span']['line'] <= n <= f['span']['end_line'] for n in changed.get(f['span']['path'], set()))}
    changed_names = {all_units[x].name.rsplit('.', 1)[-1] for x in changed_units}
    changed_names.update(functions[x]['name'].rsplit('.', 1)[-1] for x in changed_functions)
    edges = defaultdict(set)
    for call in frontend.get('production_calls', []):
        if call.get('function_id') in functions:
            edges[call['function_id']].update(_targets(call, functions))
    calls_by_test, observations_by_test = defaultdict(list), defaultdict(list)
    for call in frontend.get('calls', []):
        if call['test_id'] in tests:
            calls_by_test[call['test_id']].append(call)
    for observation in frontend.get('observations', []):
        if observation['test_id'] in tests:
            observations_by_test[observation['test_id']].append(observation)
    candidates, related_functions = [], set()
    for tid, test in sorted(tests.items(), key=lambda kv: (kv[1]['span']['path'], kv[1]['span']['start_byte'], kv[0])):
        sp = test['span']; calls = calls_by_test[tid]
        reached = _closure([x for c in calls for x in _targets(c, functions)], edges)
        changed_reached = sorted(reached & changed_functions)
        overlapping = sorted(x for x in changed.get(sp['path'], set()) if sp['line'] <= x <= sp['end_line'])
        weak = [c for c in calls if (IDENT.findall(c.get('callee', '')) or [''])[-1] in changed_names
                and not _targets(c, functions)]
        reasons = []
        if overlapping:
            reasons.append(dict(kind='original_test_overlaps_patch', new_side_lines=overlapping))
        if changed_reached:
            reasons.append(dict(kind='resolved_call_graph_reaches_changed_declaration', function_ids=changed_reached))
        if weak:
            reasons.append(dict(kind='unresolved_call_name_matches_changed_declaration', call_ids=[c['id'] for c in weak],
                                status='lexical_weak_not_binding_proof'))
        if not reasons:
            continue
        source = sources[sp['path']]
        full = _at(sources, sp)
        observations = observations_by_test[tid]
        observed_calls = {cid for o in observations if o.get('kind') == 'assertion' for cid in o.get('source_call_ids', [])}
        call_facts = [dict(evidence_id='call_' + c['id'], call_id=c['id'], span=c['span'], callee=c['callee'], role=c.get('role'),
                           resolved_targets=_targets(c, functions), target_hypotheses=c.get('targets', []),
                           assertion_source_call_link=c['id'] in observed_calls,
                           callee_identity=c.get('callee_identity'), contexts=_context_summary(c.get('contexts', []))) for c in calls]
        observed = [dict(evidence_id='observation_' + o['id'], observation_id=o['id'], span=o['span'], kind=o.get('kind'), adapter=o.get('adapter'),
                         source_call_ids=o.get('source_call_ids', []), observed_binding=_binding_summary(o.get('observed_binding')),
                         observed_span=(o.get('observed') or {}).get('span'), expected_span=(o.get('expected') or {}).get('span'), contexts=_context_summary(o.get('contexts', [])),
                         oracle_status='original_assertion_requires_contract_review') for o in observations]
        related_functions.update(reached)
        link_paths = [sp['path']]
        link_names = sorted({test['name'].rsplit('.', 1)[-1]} | {functions[f]['name'].rsplit('.', 1)[-1] for f in changed_reached}
                            | {(IDENT.findall(c.get('callee', '')) or [''])[-1] for c in weak})
        candidates.append(dict(evidence_id='test_' + digest([tid, full])[:24], seed_alias='seed_' + digest([tid, full])[:20], base_test_id=tid,
                               path=sp['path'], span=sp, body_span=test.get('body_span'), original_test=full,
                               original_test_sha256=hashlib.sha256(full.encode()).hexdigest(), selection_facts=reasons,
                               source_facts=dict(calls=call_facts, observations=observed,
                                                 result_channels=_channel_facts(source, test, calls, observations),
                                                 type_only=source.type_only,
                                                 unknowns=['Call-level assertion linkage is not per-result or per-field coverage.',
                                                           'Scope, alias, path and observation adequacy require review. Existing frontend graph bounds apply.']),
                               related_function_ids=sorted(reached), history_link_paths=link_paths,
                               history_link_identifiers=link_names,
                               evidence_ids=['source_' + digest([source.path, source.code])[:24]]))
    host_paths = sorted({c['path'] for c in candidates})
    context_paths = sorted(set(host_paths) | {p for p in changed if p in sources and is_test_path(p)})
    files = [dict(evidence_id='source_' + digest([p, sources[p].code])[:24], path=p,
                  text=sources[p].code, sha256=hashlib.sha256(sources[p].data).hexdigest(),
                  role='complete_host_test_file' if p in host_paths else 'complete_changed_source_test_file',
                  parse_error=sources[p].root.has_error) for p in context_paths]
    declarations = []
    declaration_rows = dict(functions)
    for uid in changed_units:
        u = all_units[uid]
        declaration_rows.setdefault(uid, dict(id=uid, span=_span(u.source, u.node)))
    for fid in sorted(related_functions | changed_functions | changed_units):
        f = declaration_rows[fid]
        if f['span']['path'] in context_paths:
            continue
        text = _at(sources, f['span'])
        declarations.append(dict(evidence_id='declaration_' + digest([fid, text])[:24], function_id=fid,
                                 span=f['span'], text=text, sha256=hashlib.sha256(text.encode()).hexdigest(),
                                 role='complete_bound_source_declaration_implementation_not_oracle'))
    # Preserve changed imports, constants, class headers and fields which do
    # not lie in any changed function. Each is a complete original AST node.
    block_keys = {(d['span']['path'], d['span']['start_byte'], d['span']['end_byte']) for d in declarations}
    for path, lines in sorted(changed.items()):
        if path not in sources or path in context_paths:
            continue
        source = sources[path]
        covered = [d['span'] for d in declarations if d['span']['path'] == path]
        for line in sorted(lines):
            if any(sp['line'] <= line <= sp['end_line'] for sp in covered):
                continue
            source_lines = source.data.splitlines(keepends=True)
            if line < 1 or line > len(source_lines) or not source_lines[line - 1].strip():
                continue
            line_bytes = source_lines[line - 1]
            position = sum(len(x) for x in source_lines[:line - 1]) + len(line_bytes) - len(line_bytes.lstrip(b' \t'))
            if position >= len(source.data):
                continue
            node = source.root.named_descendant_for_byte_range(position, position)
            if node == source.root:
                continue
            while node.parent is not None and node.parent != source.root and node.parent.type not in {'block', 'class_body', 'statement_block'}:
                node = node.parent
            # A class header is enough when only that header changed. Methods
            # and changed field statements are independently preserved above.
            body = child(node, 'body')
            end = body.start_byte if node.type in {'class_definition', 'class_declaration'} and body else node.end_byte
            sp = _span(source, node); sp['end_byte'] = end
            sp['end_line'] = source.data[:end].count(b'\n') + 1
            key = (path, sp['start_byte'], sp['end_byte'])
            if key not in block_keys:
                block_keys.add(key)
                text = _at(sources, sp)
                declarations.append(dict(evidence_id='declaration_' + digest([sp, text])[:24], span=sp,
                                         text=text, sha256=hashlib.sha256(text.encode()).hexdigest(),
                                         role='changed_source_declaration_or_class_header_not_oracle'))
    imports = []
    # Inventory all donor imports, not a hand-picked API list. A generator must
    # still resolve relative modules from its own host path and preserve binding.
    for path, source in sources.items():
        for name, (module, imported) in sorted(source.imports.items()):
            imports.append(dict(name=name, module=module, imported_name=imported, source_path=path,
                                source_sha256=hashlib.sha256(source.data).hexdigest(),
                                binding_scope='source_parser_inventory_not_lexical_scope_proof'))
    original_ids = set(tests)
    inventory = [dict(source_unit_id=u.id, path=u.source.path, span=_span(u.source, u.node), type_only=u.source.type_only,
                      mapped_original_test_id=u.id if u.id in original_ids else None)
                 for u in all_units.values() if u.test]
    # Strip extraction-only linkage fields in both arms. Selection and source
    # facts are computed before any trajectory access.
    public_candidates = [{k: v for k, v in c.items() if not k.startswith('history_link_')} for c in candidates]
    source_payload = dict(version=VERSION, policy=POLICY, public_issue=issue, submitted_patch=patch,
                          evidence_catalog=[dict(evidence_id='issue_' + digest(issue)[:24], kind='public_issue', field='public_issue'),
                                            dict(evidence_id='patch_' + digest(patch)[:24], kind='submitted_patch', field='submitted_patch')],
                          seeds=public_candidates, original_source_files=files,
                          related_source_declarations=declarations,
                          permitted_import_bindings=_prompt_imports(imports, set(context_paths) | {d['span']['path'] for d in declarations}, corpus['language']),
                          unknowns=['The corpus inventory is bounded. Source-only unseen tests are inventoried but are not native-ready seeds.',
                                    'Implementation bodies provide behavior context; public issue/docs must justify any new oracle.'])
    names = {x for c in candidates for x in c['history_link_identifiers']}
    paths = {x for c in candidates for x in c['history_link_paths']} | {p for p in context_paths if is_test_path(p)}
    history = _history(trajectory, corpus['language'], candidates, paths, names)
    history_payload = {**source_payload, 'trajectory_evidence': history}
    clusters = [dict(path=p, seed_aliases=[c['seed_alias'] for c in candidates if c['path'] == p]) for p in host_paths]
    batches = _batches(source_payload, history, candidates, imports, corpus['language'])
    return dict(version=VERSION, case=case, policy=POLICY, candidates=public_candidates, file_clusters=clusters, batches=batches,
                source_payload=source_payload, history_payload=history_payload, imports=imports,
                inventory=inventory, counts=dict(original_repository_tests=len(tests), selected_tests=len(candidates),
                    test_files=len(host_paths), inventory_tests=len(inventory), inventory_unmapped_tests=sum(x['mapped_original_test_id'] is None for x in inventory),
                    source_payload_bytes=len(encoded(source_payload)), history_payload_bytes=len(encoded(history_payload)),
                    related_steps=len(history['steps']), recovered_versions=len(history['recovered_source_versions']),
                    import_bindings=len(imports), batches=len(batches),
                    overflow_batches=sum(b['budget_status'] != 'within_bound' for b in batches)))


def prepare_case(case, source, *, output=None):
    source = Path(source).resolve()
    corpus = json.loads((source / 'corpus.json').read_text())
    frontend = json.loads((source / 'frontend.json').read_text())
    metadata = json.loads((source / 'case.json').read_text())
    paths = {name: source / name for name in ('corpus.json', 'frontend.json', 'case.json', 'issue.md')}
    paths.update(trajectory=Path(metadata['trajectory']), patch=Path(metadata['candidate_patch']))
    result = extract(corpus, frontend, paths['issue.md'].read_text(),
                     json.loads(paths['trajectory'].read_text()), paths['patch'].read_text(), case=case)
    result['input_receipts'] = {k: receipt(p) for k, p in paths.items()}
    result['algorithm'] = receipt(__file__)
    result['repository'] = metadata.get('repository')
    result['source'] = str(source)
    if output is not None:
        destination = Path(output); destination.mkdir(parents=True, exist_ok=True)
        (destination / 'prepared.json').write_bytes(encoded(result) + b'\n')
        (destination / 'source_payload.json').write_bytes(encoded(result['source_payload']) + b'\n')
        (destination / 'history_payload.json').write_bytes(encoded(result['history_payload']) + b'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', required=True)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = prepare_case(args.case, args.source, output=args.output)
    print(json.dumps(dict(case=args.case, **result['counts']), ensure_ascii=False))


if __name__ == '__main__':
    main()
