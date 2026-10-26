"""Source-only priority for edited inputs on a patched return-to-observation path.

This is a bounded syntactic may-dependence witness, not execution coverage,
path feasibility, an oracle, or a proof that a missing path is independence.
Unknown candidates retain the complete original fair ordering.
"""
from __future__ import annotations

from collections import defaultdict
import copy
import difflib
import hashlib
import json
import posixpath
import re

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import CALLS, Source, Unit, call_parts, child, is_test_path, units, walk
from experimental.local_helper_evidence import _writes
from experimental.modified_observation_impact import map_unchanged_span
from relational_gap.frontend import (_FrontendIndex, _add_assigned_functions, _assertion_nodes,
                                    _flow_for_test, _parameters, _resolved_targets, _test_walk, span)
from relation_search import semantic_selection
from relation_search.instrument import _program_edits
from relation_search.oracle_evidence import _modified_sources


POLICY = dict(version='patch-observation-priority-v1',
    priority='stable boolean partition of the original fair ranking; no candidates discarded',
    witness='one edited input -> bound formal -> patched returned source -> same call result -> actual observation',
    scope='bounded unique static calls; local value/control return dependencies; no heap/effect summaries',
    limits=['syntactic may dependence', 'no path feasibility', 'no oracle proof',
            'opaque calls, loops, captures, scope-uncertain writes and deleted-only patch sites unknown'],
    forbidden_inputs=['target labels', 'oracle answers', 'runtime outcomes', 'issue keywords', 'API-name rules'])
MAX_DEPTH = 5
_SYNTHETIC = {'parameter', 'receiver', 'join', 'unknown', 'may_effect', 'assertion'}
_RESOLUTIONS = {'local_symbol', 'import_symbol', 'source_import_symbol',
                'source_constructor_receiver', 'source_this_receiver', 'receiver_type', 'constructor'}
_UNSUPPORTED = {'for_statement', 'for_in_statement', 'range_clause', 'while_statement',
                'try_statement', 'with_statement', 'switch_statement', 'expression_switch_statement',
                'type_switch_statement', 'select_statement', 'go_statement', 'defer_statement',
                'lambda', 'func_literal', 'function_expression', 'arrow_function'}
_WRITES = {'assignment', 'assignment_statement', 'short_var_declaration', 'variable_declarator',
           'var_spec', 'const_spec', 'type_spec', 'type_alias', 'augmented_assignment'}


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _extent(source, node):
    return dict(path=source.path, start_byte=node['start_byte'], end_byte=node['end_byte'])


def _patch_facts(sources, patch):
    """Only available, exact new-side added lines; deletion boundaries are not code."""
    added = defaultdict(dict); regions=defaultdict(list); unknowns = []; path = None; line = 0
    hunk_added = hunk_removed = False; removed_run=[]; added_run=[]
    def flush_run():
        if not added_run:
            if removed_run:unknowns.append(dict(reason='patch_deleted_bytes_no_new_source',path=path))
            removed_run.clear();return
        source=sources.get(path)
        if source is not None and source.origin=='repository':
            code_lines=source.data.splitlines(keepends=True)
            first=added_run[0][0]
            if 0<first<=len(code_lines) and all(0<n<=len(code_lines) and code_lines[n-1].rstrip(b'\r\n')==text.encode() for n,text in added_run):
                before='\n'.join(removed_run).encode();after='\n'.join(text for _,text in added_run).encode()
                start=sum(map(len,code_lines[:first-1]))
                if source.data[start:start+len(after)]==after:
                    for tag,_,_,left,right in difflib.SequenceMatcher(a=before,b=after,autojunk=False).get_opcodes():
                        if tag!='equal' and left<right:regions[path].append((start+left,start+right))
                        elif tag=='delete':unknowns.append(dict(reason='patch_deleted_bytes_no_new_source',path=path))
                else:unknowns.append(dict(reason='patch_added_block_source_mismatch',path=path))
        removed_run.clear();added_run.clear()
    def finish():
        flush_run()
        if hunk_removed and not hunk_added:
            unknowns.append(dict(reason='patch_deletion_only_hunk', path=path))
    for text in patch.splitlines():
        if text.startswith('+++ '):
            finish(); hunk_added = hunk_removed = False
            path = text[6:] if text.startswith('+++ b/') else None
        elif text.startswith('@@'):
            finish(); hunk_added = hunk_removed = False
            match = re.search(r'\+(\d+)', text)
            line = int(match[1]) if match else 0
        elif path and text.startswith('+'):
            added[path][line] = text[1:];added_run.append((line,text[1:])); line += 1; hunk_added = True
        elif path and text.startswith('-') and not text.startswith('---'):
            hunk_removed = True;removed_run.append(text[1:])
        elif text.startswith(' '):
            flush_run()
            line += 1
    finish()
    verified = defaultdict(set)
    for path, rows in added.items():
        source = sources.get(path)
        if source is None or source.origin != 'repository':
            unknowns.append(dict(reason='patch_final_repository_source_unavailable', path=path)); continue
        lines = source.code.splitlines()
        for number, text in rows.items():
            if 0 < number <= len(lines) and lines[number-1] == text:
                verified[path].add(number)
            else:
                unknowns.append(dict(reason='patch_new_line_source_mismatch', path=path, line=number))
    if not any(verified.values()):
        unknowns.append(dict(reason='no_available_modified_source_line'))
    return verified,regions,unknowns


def _scope_unknown(unit):
    for node in walk(unit.body, stop_functions=True):
        if node.type in _UNSUPPORTED:
            return 'unsupported_control_or_capture:'+node.type
        if node.type in _WRITES:
            parent = node.parent
            while parent is not None and parent != unit.body:
                if parent.type in {'if_statement', 'else_clause', 'elif_clause', 'block', 'statement_block'}:
                    return 'scope_uncertain_local_write'
                parent = parent.parent
    return None


def _module_writes(source):
    """Lexical module declarations/assignments, excluding nested function/class bodies."""
    result=[]
    for node in walk(source.root,stop_functions=True):
        parent=node.parent; nested=False
        while parent is not None and parent!=source.root:
            if parent.type in {'function_definition','function_declaration','method_declaration',
                               'class_definition','class_declaration','func_literal','arrow_function','function_expression'}:
                nested=True;break
            parent=parent.parent
        if not nested:
            result.extend((name,node) for name in _writes(source,node))
    return result


class Analyzer:
    def __init__(self, corpus, frontend, patch):
        self.corpus = corpus; self.frontend = frontend
        self.resolution = frontend.get('module_resolution', {})
        rows = [Source(path, row['code'], row.get('language', corpus['language']),
                       row.get('origin', 'repository'), row.get('step'), row.get('written_path'))
                for path, row in sorted(corpus['sources'].items())]
        self.index = _FrontendIndex(rows, patch, module_aliases=self.resolution.get('aliases'),
                                    module_base_url=self.resolution.get('base_url'))
        _add_assigned_functions(self.index, rows)
        for unit in self.index.units.values():
            unit.params=[p['name'] for p in _parameters(unit) if p['name'] is not None]
        self.index.flows={}
        self.patch_lines,self.patch_regions,self.patch_unknowns = _patch_facts(self.index.sources, patch)
        self.observations = defaultdict(list)
        for row in frontend.get('observations', []):
            self.observations[row['test_id']].append(row)
        self.summary_cache = {};self.may_cache={}

    def _variant(self, owner):
        # Only the changed test owner is reparsed. Production source and its
        # summaries remain immutable; no original local flow is reused.
        current = copy.copy(self.index)
        current.sources = dict(self.index.sources, **{owner.path: owner})
        current.units = {uid: unit for uid, unit in self.index.units.items() if unit.source.path != owner.path}
        found, _ = units(owner)
        current.units.update({unit.id: unit for unit in found})
        current.by_name = defaultdict(list); current.by_file_name = defaultdict(list)
        for unit in current.units.values():
            current.by_name[unit.name].append(unit)
            current.by_file_name[unit.source.path, unit.name].append(unit)
        current.flows = {uid: flow for uid, flow in self.index.flows.items() if uid in current.units and current.units[uid].source.path != owner.path}
        _add_assigned_functions(current, [owner])
        for unit in current.units.values():
            if unit.source.path==owner.path:
                unit.params=[p['name'] for p in _parameters(unit) if p['name'] is not None]
        return current

    def _target(self, index, unit, flow, call, *, exact_arguments=True):
        node = next((n for n in walk(unit.body, stop_functions=True) if n.type in CALLS
                     and n.start_byte == flow.nodes[call.node]['start_byte']
                     and n.end_byte == flow.nodes[call.node]['end_byte']), None)
        if node is None: return None, 'call_source_node_unavailable'
        fn, args = call_parts(node)
        if any('spread' in arg.type or 'splat' in arg.type or 'variadic' in arg.type for arg in args):
            return None, 'spread_actual_unknown'
        name = unit.source.text(fn); root = name.split('.', 1)[0]
        module_writes={written for written,_ in _module_writes(unit.source)}
        if root in unit.source.imports and root in module_writes:
            return None,'module_import_rebound_unknown'
        local_writes = {name for statement in walk(unit.body, stop_functions=True)
                        for name in _writes(unit.source, statement)}
        if root in unit.params or root in local_writes:
            # Named object receivers are allowed only with an independently
            # rebound source-constructor proof below, not spelling/type alone.
            rebound = True
        else: rebound = False
        targets = _resolved_targets(index, unit, node, call)
        selected = [(uid, reason) for uid, reason in targets if reason in _RESOLUTIONS or reason == 'package_symbol']
        if unit.source.language=='go' and fn.type=='identifier' and not rebound:
            # A bare Go function can live in another file of the same source
            # package. Prove that package/directory binding independently of
            # Index's fallback based only on globally unique spelling.
            package=index.go_packages.get(unit.source.path)
            local=[candidate for candidate in index.by_name.get(name,[])
                   if not candidate.owner and not candidate.test
                   and posixpath.dirname(candidate.source.path)==posixpath.dirname(unit.source.path)
                   and package and index.go_packages.get(candidate.source.path)==package]
            selected=[(candidate.id,'same_directory_go_static_symbol') for candidate in local]
        if rebound:
            selected = [(uid, reason) for uid, reason in selected
                        if reason in {'source_constructor_receiver', 'source_this_receiver'}
                        or (not exact_arguments and unit.source.language=='go' and '.' in name and reason=='receiver_type')]
        if len(selected) != 1: return None, 'callee_unresolved_or_ambiguous'
        uid, reason = selected[0]; target = index.units[uid]
        binding_name=target.owner or target.name
        if any(written==binding_name
               and not (target.source.language=='go' and target.owner and statement.type in {'type_spec','type_alias'})
               and not (statement.start_byte<=target.node.start_byte and target.node.end_byte<=statement.end_byte)
               for written,statement in _module_writes(target.source)):
            return None,'target_module_binding_rebound_unknown'
        if reason == 'package_symbol':
            imported = unit.source.imports.get(root)
            roots = self.resolution.get('go_modules', {})
            expected = []
            if imported:
                for directory, module in roots.items():
                    relative = posixpath.relpath(posixpath.dirname(target.source.lookup_path), directory or '.')
                    expected.append(module.rstrip('/')+('/'+relative if relative != '.' else ''))
            if not imported or imported[0] not in expected:
                return None, 'go_import_path_not_proved'
        if target.test or is_test_path(target.source.path): return None, 'custom_test_helper_unsupported'
        parameters = _parameters(target)
        if not exact_arguments:
            return (target, {}, reason), None
        if (any(p['name'] is None or p['default'] is not None or p['variadic'] for p in parameters)
                or call.keywords or len(call.args) != len(parameters)):
            return None, 'non_exact_argument_binding'
        target.params = [p['name'] for p in parameters]
        return (target, {p['name']: call.args[p['index']].id for p in parameters}, reason), None

    def _may_reach(self, index, target):
        cache_key=(target.id,hashlib.sha256(target.source.data).hexdigest())
        if cache_key in self.may_cache:return self.may_cache[cache_key]
        pending = [(target, [])]; seen = set(); result = []; unknowns = set()
        while pending:
            unit, chain = pending.pop(0)
            if unit.id in seen: continue
            seen.add(unit.id)
            if len(chain) >= MAX_DEPTH:
                unknowns.add('may_call_depth_exhausted'); continue
            lines = self.patch_lines.get(unit.source.path, set())
            if unit.source.origin == 'repository' and not is_test_path(unit.source.path):
                for number in sorted(lines):
                    if unit.body.start_point.row+1 <= number <= unit.body.end_point.row+1:
                        # This explicitly weaker witness names the entire source
                        # callee's changed line, not a proved returned dependency.
                        code_lines = unit.source.data.splitlines(keepends=True)
                        start = sum(map(len, code_lines[:number-1])); end = start+len(code_lines[number-1].rstrip(b'\r\n'))
                        result.append(dict(patch_function_id=unit.id, patch_span=dict(path=unit.source.path,start_byte=start,end_byte=end),
                            patch_code=unit.source.data[start:end].decode(), source_sha256=hashlib.sha256(unit.source.data).hexdigest(),
                            call_chain=chain, basis='changed_callee_body_may_reach_not_return_summary'))
                        self.may_cache[cache_key]=(result,unknowns)
                        return result,unknowns
            flow = index.flow(unit.id)
            for call in flow.calls:
                resolved, reason = self._target(index, unit, flow, call, exact_arguments=False)
                if resolved is None:
                    unknowns.add(reason); continue
                callee, _, resolution = resolved
                pending.append((callee, [*chain, dict(caller_id=unit.id,callee_id=callee.id,
                    call_span=_extent(unit.source,flow.nodes[call.node]),resolution=resolution)]))
        self.may_cache[cache_key]=(result,unknowns)
        return result, unknowns

    def _may_witnesses(self, index, unit, flow, roots, changes, q, old, current, actual):
        # The original Flow is a conservative graph. Unlike strict projection,
        # its call-argument and receiver-effect dependencies are retained here.
        # The join always uses one concrete call in one actual observation slice.
        actual_slice = flow.slice(roots); result = []; unknowns = set()
        for call in flow.calls:
            if call.node not in actual_slice: continue
            resolved, reason = self._target(index, unit, flow, call, exact_arguments=False)
            if resolved is None:
                unknowns.add(reason); continue
            target, _, resolution = resolved
            input_roots = [value.id for value in call.args]+[value.id for value in call.keywords.values()]
            if call.receiver is not None: input_roots.append(call.receiver.id)
            input_nodes = flow.slice(input_roots)
            reachable, reasons = self._may_reach(index, target); unknowns.update(reasons)
            for change in changes:
                if change['role']=='semantic_expected' or change['before']==change['after']: continue
                extent=change['span']
                if extent['start_byte']==extent['end_byte']:
                    unknowns.add('deleted_input_no_modified_seed'); continue
                seeds=[nid for nid in input_nodes if flow.nodes[nid]['kind'] not in _SYNTHETIC
                       and extent['start_byte']<flow.nodes[nid]['end_byte'] and flow.nodes[nid]['start_byte']<extent['end_byte']]
                if not seeds: continue
                for item in reachable:
                    result.append(dict(item,observation_id=q['id'],original_assertion_span=old,modified_assertion_span=current,
                        actual_span=span(unit.source,actual), original_edit_span=change['original_span'],modified_edit_span=extent,
                        input_nodes=[dict(span=_extent(unit.source,flow.nodes[nid]),
                            code=unit.source.data[flow.nodes[nid]['start_byte']:flow.nodes[nid]['end_byte']].decode()) for nid in sorted(seeds)],
                        call_chain=[dict(caller_id=unit.id,callee_id=target.id,call_span=_extent(unit.source,flow.nodes[call.node]),resolution=resolution),*item['call_chain']],
                        status='conservative_same_call_may_path_not_execution_or_oracle_proof',
                        unknowns=['may_call_arguments_and_receiver_effects','path_feasibility_unproved','returned_patch_dependency_unproved']))
        return result,unknowns

    def _summary(self, index, unit, stack):
        if unit.id in stack or len(stack) >= MAX_DEPTH:
            return dict(params=set(), nodes=set(), patches=[], unknowns={'recursive_or_depth_unknown'})
        key = (unit.id, hashlib.sha256(unit.source.data).hexdigest())
        if key in self.summary_cache: return self.summary_cache[key]
        unknown = _scope_unknown(unit)
        if unknown or unit.source.root.has_error:
            return dict(params=set(), nodes=set(), patches=[], unknowns={unknown or 'parse_error'})
        flow = index.flow(unit.id)
        if not flow.returns:
            return dict(params=set(), nodes=set(), patches=[], unknowns={'no_explicit_return'})
        result = self._slice(index, unit, flow, flow.returns, stack+(unit.id,))
        if not result['unknowns']: self.summary_cache[key] = result
        return result

    def _slice(self, index, unit, flow, roots, stack, *, collect_patch=True):
        nodes = set(); params = set(); patches = []; unknowns = set(); pending = list(roots)
        calls = {call.node: call for call in flow.calls}
        while pending:
            nid = pending.pop()
            if nid in nodes: continue
            nodes.add(nid); node = flow.nodes[nid]
            if node['kind'] in {'unknown', 'may_effect', 'field_read', 'field_write', 'receiver'}:
                unknowns.add('heap_or_unknown_dependency:'+node['kind']); continue
            if node['kind'] == 'parameter': params.add(node['parameter']); continue
            if nid not in calls:
                pending.extend(dep for dep in flow.edges.get(nid, ()) if flow.edge_kinds.get((nid, dep)) in {'value', 'control'})
                continue
            call = calls[nid]
            resolved, reason = self._target(index, unit, flow, call)
            pending.extend(dep for dep in flow.edges.get(nid, ()) if flow.edge_kinds.get((nid, dep)) == 'control')
            if resolved is None: unknowns.add(reason); continue
            target, arguments, resolution = resolved
            summary = self._summary(index, target, stack)
            unknowns.update(summary['unknowns'])
            pending.extend(arguments[name] for name in summary['params'] if name in arguments)
            for item in summary['patches']:
                dependencies = self._slice(index, unit, flow,
                    [arguments[name] for name in item['formal_dependencies'] if name in arguments], stack, collect_patch=False)
                unknowns.update(dependencies['unknowns'])
                patches.append(dict(item, formal_dependencies=sorted(dependencies['params']),
                    input_node_ids=sorted(dependencies['nodes']),
                    call_chain=[dict(caller_id=unit.id, callee_id=target.id,
                        call_span=_extent(unit.source, node), resolution=resolution), *item['call_chain']]))
        if collect_patch and unit.source.origin == 'repository' and not unit.test and not is_test_path(unit.source.path):
            changed = self.patch_lines.get(unit.source.path, set())
            for nid in sorted(nodes):
                node = flow.nodes[nid]
                if (node['kind'] in _SYNTHETIC or not any(node['line'] <= number <= node['end_line'] for number in changed)
                    or not any(left<node['end_byte'] and node['start_byte']<right for left,right in self.patch_regions.get(unit.source.path,[]))): continue
                dependency = self._slice(index, unit, flow, [nid], stack, collect_patch=False)
                unknowns.update(dependency['unknowns'])
                patches.append(dict(patch_span=_extent(unit.source, node), patch_code=unit.source.data[node['start_byte']:node['end_byte']].decode(),
                    source_sha256=hashlib.sha256(unit.source.data).hexdigest(), patch_function_id=unit.id,
                    formal_dependencies=sorted(dependency['params']), input_node_ids=sorted(dependency['nodes']), call_chain=[]))
        return dict(params=params, nodes=nodes, patches=patches if not unknowns else [], unknowns=unknowns)

    def evidence(self, candidate):
        clean = dict(candidate, edits=_program_edits(candidate)); base = clean['base_test_id']
        record = dict(strong_priority=False, may_priority=False, witnesses=[], may_witnesses=[], unknowns=[], patch_unknowns=self.patch_unknowns,
                      scope='modified_test_and_final_repository_return_may_dependencies')
        try:
            sources, owner, changes, imports, unknowns = _modified_sources(self.corpus, clean)
            if len({(e['span']['path'], e['span']['start_byte'], e['span']['end_byte']) for e in clean['edits']}) != len(clean['edits']):
                raise ValueError('duplicate_edit_coordinates')
            index = self._variant(owner); original = self.corpus['tests'][base]
            definition = original.get('definition_span') or original['span']
            anchor = dict(path=owner.path, start_byte=definition['start_byte'], end_byte=definition['start_byte']+1)
            mapped = map_unchanged_span(anchor, changes)
            matches = [u for u in index.units.values() if u.source.path == owner.path and mapped and u.node.start_byte == mapped['start_byte']]
            if original.get('owner_kind') == 'module_script':
                matches = [Unit(owner, owner.root, owner.root, '<script>', test=True)]
                index.units[matches[0].id] = matches[0]
            if len(matches) != 1: raise ValueError('modified_test_identity_unknown')
            unit = matches[0]
            scope_unknown=_scope_unknown(unit)
            if scope_unknown: record['unknowns'].append(scope_unknown)
            flow = _flow_for_test(index, unit, list(_test_walk(unit.body)))
            record.update(modified_owner_sha256=hashlib.sha256(owner.data).hexdigest(), input_changes=changes, import_bindings=imports)
            record['unknowns'].extend(row['reason'] for row in unknowns)
            for q in self.observations[base]:
                old = q.get('assertion_span') or q['span']; current = map_unchanged_span(old, changes)
                if current is None:
                    record['unknowns'].append('changed_assertion_unknown'); continue
                if owner.data[current['start_byte']:current['end_byte']] != self.corpus['sources'][old['path']]['code'].encode()[old['start_byte']:old['end_byte']]:
                    raise ValueError('assertion_source_identity_mismatch')
                assertion=None
                for item in flow.assertions:
                    statement,_,_,_=_assertion_nodes(owner,item,unit)
                    if statement is not None and statement.start_byte==current['start_byte'] and statement.end_byte==current['end_byte']:
                        assertion=item;break
                if assertion is None:
                    record['unknowns'].append('modified_observation_unavailable'); continue
                _, actual, _, _ = _assertion_nodes(owner, assertion, unit)
                roots = [n['id'] for n in flow.nodes if actual is not None and n['kind'] not in _SYNTHETIC
                         and n['start_byte'] == actual.start_byte and n['end_byte'] == actual.end_byte]
                summary = self._slice(index, unit, flow, roots, (unit.id,)) if not scope_unknown else dict(patches=[],unknowns={scope_unknown})
                record['unknowns'].extend(summary['unknowns'])
                may_witnesses,may_unknowns=self._may_witnesses(index,unit,flow,roots,changes,q,old,current,actual) if actual is not None else ([],{'actual_unavailable'})
                record['may_witnesses'].extend(may_witnesses);record['unknowns'].extend(may_unknowns)
                for item in summary['patches']:
                    for change in changes:
                        if change['role'] == 'semantic_expected' or change['before'] == change['after']: continue
                        extent = change['span']
                        if extent['start_byte'] == extent['end_byte']:
                            record['unknowns'].append('deleted_input_no_modified_seed'); continue
                        seeds = [nid for nid in item['input_node_ids'] if flow.nodes[nid]['kind'] not in _SYNTHETIC
                                 and extent['start_byte'] < flow.nodes[nid]['end_byte'] and flow.nodes[nid]['start_byte'] < extent['end_byte']]
                        if not seeds or not item['call_chain']: continue
                        record['witnesses'].append(dict(item, observation_id=q['id'], original_assertion_span=old,
                            modified_assertion_span=current, actual_span=span(owner, actual),
                            original_edit_span=change['original_span'], modified_edit_span=extent,
                            input_nodes=[dict(span=_extent(owner, flow.nodes[nid]),
                                code=owner.data[flow.nodes[nid]['start_byte']:flow.nodes[nid]['end_byte']].decode()) for nid in sorted(seeds)],
                            status='complete_source_return_may_path_not_execution_or_oracle_proof'))
        except (ValueError, KeyError, TypeError, IndexError, RecursionError, UnicodeError) as error:
            record['unknowns'].append(str(error)); record['witnesses'] = [];record['may_witnesses']=[]
        record['strong_priority'] = bool(record['witnesses'])
        record['may_priority'] = bool(record['witnesses'] or record['may_witnesses'])
        # One deterministic witness per q/edit/concrete outer call. The boolean
        # is unchanged; this is not an inventory of all feasible/structural paths.
        for key in ('witnesses','may_witnesses'):
            representatives={}
            for row in sorted(record[key],key=lambda item:(len(item['call_chain']),item['patch_span']['path'],item['patch_span']['start_byte'],item['patch_span']['end_byte'])):
                call=row['call_chain'][0]['call_span']
                identity=(row['observation_id'],tuple(sorted(row['original_edit_span'].items())),tuple(sorted(call.items())))
                representatives.setdefault(identity,row)
            record[key]=list(representatives.values())
        record['witness_material']='one deterministic shortest representative per observation/edit/outer call; not all-path coverage'
        record['unknowns'] = sorted(set(record['unknowns']))
        return record


def select(corpus, frontend, candidates, patch, budget=16, *, mode='strict'):
    """Complete source-only ranking; model-slot eligibility stays in its caller."""
    if not isinstance(patch, str): raise ValueError('patch must be source text')
    if mode not in {'strict','may'}: raise ValueError('unknown priority mode')
    candidates = list(candidates)
    normalized = [dict(c, edits=_program_edits(c)) for c in candidates]
    baseline = semantic_selection.select(corpus, normalized, budget=budget)
    analyzer = Analyzer(corpus, frontend, patch); by_id = {c['id']: c for c in candidates}
    try:
        ranking = [dict(row, baseline_rank=row['rank'], evidence=analyzer.evidence(by_id[row['id']]))
                   for row in baseline['ranking']]
        priority='strong_priority' if mode=='strict' else 'may_priority'
        ranking.sort(key=lambda row: (not row['evidence'][priority], row['baseline_rank']))
        for rank, row in enumerate(ranking, 1): row.update(rank=rank, selected=rank <= budget)
        return dict(selected=[by_id[row['id']] for row in ranking if row['selected']], ranking=ranking,
                    unselected_ids=[row['id'] for row in ranking if not row['selected']], budget=budget,
                    input_count=len(candidates), selected_count=min(budget, len(candidates)), policy=POLICY,
                    policy_sha256=_sha(POLICY), patch_sha256=hashlib.sha256(patch.encode()).hexdigest(),
                    patch_unknowns=analyzer.patch_unknowns,mode=mode,
                    priority_candidates=sum(row['evidence'][priority] for row in ranking),
                    strong_candidates=sum(row['evidence']['strong_priority'] for row in ranking),
                    may_candidates=sum(row['evidence']['may_priority'] for row in ranking))
    finally:
        for method in (Index.module_paths, Index.reach, Index.field_factors): method.cache_clear()
