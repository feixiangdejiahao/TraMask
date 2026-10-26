"""Recompute local observation obligations after the actual candidate edits.

Original observation IDs and original edit positions own scheduling identities.
Modified byte positions are evidence only. The graph is a conservative local
may-dependence model, not a semantic oracle, path-feasibility or alias proof.
"""
from __future__ import annotations

from collections import OrderedDict, defaultdict
import copy
import hashlib
import json

from anchor_retrieval.index import Index
from anchor_retrieval.syntax import Source, Unit
from prototypes.singleton_oracle_slots import assertion_inventory
from relational_gap.frontend import (_assertion_nodes, _bindings, _flow_for_test,
                                    _test_walk, expression, span)
from relation_search import impact_selection as old, semantic_selection
from relation_search.instrument import _program_edits
from relation_search.oracle_evidence import _modified_sources


POLICY = dict(version='modified-observation-impact-v2',
    dependence='reparse edited owner; local actual minus expected-value backward slices',
    observation_identity='original unchanged assertion ID aligned by exact UTF-8 edit offsets',
    port_identity='original base test and original edit path/start/end/role, independent of modified offsets',
    ranking='same greedy uncovered q then q/port, every fourth original shape exploration, budget sixteen',
    binding='rebuild local names, receiver state versions and calls; never reuse original flow nodes',
    unknown='deleted values, failed alignment, unsupported effects and unresolved call targets stay explicit',
    scope='one changed source owner; cross-file return/effect summaries are not imported',
    limits=['may dependence only','no path feasibility proof','no global/heap alias proof',
            'no cross-file effect summary','absence of path does not establish independence'],
    forbidden_inputs=['target labels','model responses','oracle cache','runtime outcomes','issue text'])


def _sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def map_unchanged_span(extent, changes):
    """Same half-open, UTF-8 alignment contract as oracle_evidence aliases."""
    shift=0
    for change in changes:
        before=change['original_span']
        if before['path']!=extent['path']:
            continue
        if before['end_byte']<=extent['start_byte']:
            shift+=len(change['after'].encode())-len(change['before'].encode())
        elif before['start_byte']<extent['end_byte']:
            return None
    return dict(path=extent['path'],start_byte=extent['start_byte']+shift,end_byte=extent['end_byte']+shift)


def _port(base, change):
    extent=change['original_span']
    return _sha([base,extent['path'],extent['start_byte'],extent['end_byte'],change['role']])


class Analyzer:
    """Cache a bounded set of local graphs; share original source parse cache."""
    def __init__(self,corpus,frontend,cache_size=8,graph_source='modified'):
        if graph_source not in {'original','modified'}:raise ValueError('unknown graph source')
        self.corpus=corpus;self.frontend=frontend;self.cache_size=cache_size
        self.graph_source=graph_source;self.original_owners={}
        self.rows=defaultdict(lambda:dict(observations=[],bindings=[]))
        for kind in ('observations','bindings'):
            for row in frontend.get(kind,[]):
                self.rows[row['test_id']][kind].append(row)
        self.cache=OrderedDict();self.graph_builds=0;self.graph_cache_hits=0

    def _graph(self,owner,base,changes):
        key=_sha([owner.path,owner.code,owner.imports,base])
        if key in self.cache:
            self.graph_cache_hits+=1;self.cache.move_to_end(key)
            return self.cache[key]
        if owner.root.has_error:
            raise ValueError('modified_owner_parse_error')
        index=Index([owner],'')
        try:
            original_test=self.corpus['tests'][base]
            if original_test.get('owner_kind')=='module_script':
                unit=Unit(owner,owner.root,owner.root,'<script>',test=True);index.units[unit.id]=unit
                identity_basis='module_script_root'
            else:
                # IDs contain the definition line: edits in a decorator may
                # shift it. Anchor the surviving definition's first byte, not
                # its old ID, spelling, or entire body (which is being edited).
                definition=original_test.get('definition_span')
                if not definition:
                    raise ValueError('original_definition_span_missing')
                anchor=dict(path=definition['path'],start_byte=definition['start_byte'],
                            end_byte=definition['start_byte']+1)
                mapped=map_unchanged_span(anchor,changes)
                if mapped is None:
                    raise ValueError('modified_definition_anchor_replaced')
                prior=self.corpus['sources'][owner.path]['code'].encode()[anchor['start_byte']:anchor['end_byte']]
                if owner.data[mapped['start_byte']:mapped['end_byte']]!=prior:
                    raise ValueError('modified_definition_anchor_source_mismatch')
                matches=[unit for unit in index.units.values() if unit.source.path==owner.path
                         and unit.node.start_byte==mapped['start_byte']]
                if len(matches)!=1:
                    raise ValueError('modified_owner_identity_not_recovered')
                unit=matches[0];identity_basis='exact_mapped_definition_start'
            nodes=list(_test_walk(unit.body));flow=_flow_for_test(index,unit,nodes)
            positions={(node.start_byte,node.end_byte):node for node in nodes}
            observations=defaultdict(list)
            for assertion in flow.assertions:
                statement,actual,expected,predicate=_assertion_nodes(owner,assertion,unit)
                if statement is None:
                    node=flow.nodes[assertion.node]
                    statement=positions.get((node['start_byte'],node['end_byte']))
                if statement is None or actual is None:
                    continue
                extent=span(owner,statement)
                observations[old._key(extent)].append(dict(span=extent,observed=expression(owner,actual),
                    expected=expression(owner,expected),predicate=predicate,adapter=assertion.assertion_adapter))
            result=dict(flow=flow,observations=observations,bindings=_bindings(unit,nodes),
                test_identity=dict(original_id=base,analyzed_unit_id=unit.id,basis=identity_basis))
            self.graph_builds+=1
            self.cache[key]=result
            while len(self.cache)>self.cache_size:self.cache.popitem(last=False)
            return result
        finally:
            # Class-level memoized Index methods otherwise retain every graph.
            for method in (Index.module_paths,Index.reach,Index.field_factors):method.cache_clear()

    def evidence(self,candidate):
        clean=dict(candidate,edits=_program_edits(candidate));base=clean['base_test_id']
        source_rows=self.rows[base]
        try:
            inventory=assertion_inventory(self.corpus,source_rows,clean) if not candidate.get('is_source_profile') else []
        except (KeyError,ValueError,IndexError,UnicodeDecodeError):inventory=[]
        editable={old._key(row['span']):row for row in inventory if row['editable']}
        record=dict(eligible=bool(editable),editable_assertions=len(editable),obligations=[],
            balanced_observation_ids=[],unknowns=[],edit_seeds=[],assertion_alignment=[],modified_calls=[],
            dependence_status=self.graph_source+'_source_local_may_impact',coordinate_source=self.graph_source)
        if not editable:
            record['unknowns'].append('no_unchanged_editable_assertion');return record
        try:
            if len({old._key(e['span']) for e in clean['edits']})!=len(clean['edits']):
                raise ValueError('ambiguous_duplicate_edit_span')
            _,owner,changes,imports,unknowns=_modified_sources(self.corpus,clean)
            record['unknowns'].extend(row['reason'] for row in unknowns)
            if self.graph_source=='original':
                if owner.path not in self.original_owners:
                    self.original_owners[owner.path]=Source(owner.path,self.corpus['sources'][owner.path]['code'],
                        owner.language,owner.origin,owner.step,owner.written_path)
                owner=self.original_owners[owner.path];imports=[]
            current=self._graph(owner,base,changes if self.graph_source=='modified' else [])
        except (ValueError,KeyError,IndexError,TypeError,RecursionError) as error:
            record['unknowns'].append(str(error) if isinstance(error,ValueError) else type(error).__name__)
            return record
        flow=current['flow']
        record.update(modified_owner_sha256=hashlib.sha256(owner.data).hexdigest(),
                      modified_import_bindings=imports,test_identity=current['test_identity'])
        seeds=[]
        for change in changes:
            if change['role']=='semantic_expected' or change['before']==change['after']:continue
            if self.graph_source=='modified' and not change['after']:
                nodes=set();record['unknowns'].append('deleted_input_no_modified_value_seed:'+change['id'])
            else:
                extent=change['span'] if self.graph_source=='modified' else change['original_span']
                nodes=old._edit_seeds(flow,[(change['original_edit_index'],dict(span=extent))])[0][2]
            seeds.append((change,nodes))
            record['edit_seeds'].append(dict(edit_index=change['original_edit_index'],
                original_span=change['original_span'],modified_span=change['span'],
                node_ids=sorted(nodes),port_id=_port(base,change)))
            if not nodes:record['unknowns'].append('no_'+self.graph_source+'_dependence_seed:'+change['id'])
        for q in source_rows['observations']:
            original=q.get('assertion_span') or q.get('span')
            if not original or old._key(original) not in editable:continue
            modified=map_unchanged_span(original,changes if self.graph_source=='modified' else [])
            matches=current['observations'].get(old._key(modified),[]) if modified else []
            if len(matches)!=1:
                record['unknowns'].append('modified_observation_alignment_unknown:'+q['id']);continue
            now=matches[0]
            if owner.data[modified['start_byte']:modified['end_byte']].decode()!=editable[old._key(original)]['code']:
                record['unknowns'].append('aligned_assertion_source_changed:'+q['id']);continue
            record['assertion_alignment'].append(dict(observation_id=q['id'],original_span=original,modified_span=modified))
            actual=old._roots(flow,now.get('observed'))
            expected,basis=old._expected_roots(flow,now,editable[old._key(original)],current['bindings'])
            if not actual or expected is None:
                record['unknowns'].append('modified_expression_root_unknown:'+q['id']);continue
            actual_slice=old._slice(flow,actual);expected_slice=old._slice(flow,expected,expected_value=True)
            for change,nodes in seeds:
                affected=nodes&actual_slice
                if affected&expected_slice:record['balanced_observation_ids'].append(q['id'])
                affected-=expected_slice
                if not affected:continue
                path=old._path(flow,actual,affected)
                kinds=[flow.edge_kinds.get((right,left),'unknown') for left,right in zip(path,path[1:])]
                record['obligations'].append(dict(observation_id=q['id'],port_id=_port(base,change),
                    edit_index=change['original_edit_index'],assertion_span=original,
                    actual_span=q.get('observed',{}).get('span'),expected_span=(q.get('expected') or {}).get('span'),
                    modified_assertion_span=modified,modified_actual_span=now['observed']['span'],
                    modified_expected_span=(now.get('expected') or {}).get('span'),
                    actual_root_ids=actual,expected_root_ids=expected,
                    expected_dependency_basis=basis.replace('original_',self.graph_source+'_'),
                    expected_value_slice_node_ids=sorted(expected_slice),observed=now['observed']['text'],
                    expected=(now.get('expected') or {}).get('text'),
                    expected_status='unchanged_expression_without_same_modified_edit_dependency',
                    path=[dict(old._path_node(flow,node),text_basis='complete_'+self.graph_source+'_source_span')
                          for node in path],edge_kinds=kinds))
                if 'control' in kinds:record['unknowns'].append('control_path_feasibility_unproved')
        for call in flow.calls:
            node=flow.nodes[call.node]
            targets=[dict(function_id=target,reason=reason) for target,reason in call.targets]
            record['modified_calls'].append(dict(callee=call.name,
                span=dict(path=owner.path,start_byte=node['start_byte'],end_byte=node['end_byte']),targets=targets))
            if not targets:record['unknowns'].append('unresolved_modified_call_target:'+node.get('call',''))
        record['balanced_observation_ids']=sorted(set(record['balanced_observation_ids']))
        record['unknowns']=sorted(set(record['unknowns']))
        return record


def select(corpus,frontend,candidates,budget=16,*,graph_source='modified'):
    """Keep original greedy scheduling; replace only obligation evidence."""
    if type(budget) is not int or budget<0:raise ValueError('budget must be nonnegative integer')
    candidates=list(candidates);by_id={c['id']:c for c in candidates}
    clean=[dict(c,edits=_program_edits(c)) for c in candidates]
    baseline=semantic_selection.select(corpus,clean,budget=len(clean))
    analyzer=Analyzer(corpus,frontend,graph_source=graph_source);records=[]
    for row in baseline['ranking']:
        evidence=analyzer.evidence(by_id[row['id']])
        pairs={(o['observation_id'],o['port_id']) for o in evidence['obligations']}
        records.append(dict(id=row['id'],base_test_id=row['base_test_id'],baseline_rank=row['rank'],
            shape_id=row['shape_id'],evidence=evidence,_pairs=pairs,_observations={q for q,p in pairs}))
    pending=[r for r in records if r['evidence']['eligible']];ranking=[];covered=set();ports=set()
    while pending:
        explore=(len(ranking)+1)%4==0
        def priority(row):return (-len(row['_observations']-covered),-len(row['_pairs']-ports),row['baseline_rank'])
        chosen=min(pending,key=(lambda row:row['baseline_rank']) if explore else priority);pending.remove(chosen)
        chosen.update(new_observation_count=len(chosen['_observations']-covered),
            new_observation_port_count=len(chosen['_pairs']-ports),
            selection_reason='shape_exploration' if explore else 'uncovered_impact')
        covered.update(chosen['_observations']);ports.update(chosen['_pairs']);ranking.append(chosen)
    eligible_count=len(ranking)
    ranking.extend(dict(r,selection_reason='ineligible_assertion_interface',new_observation_count=0,
        new_observation_port_count=0) for r in records if not r['evidence']['eligible'])
    for rank,row in enumerate(ranking,1):
        row.pop('_pairs');row.pop('_observations');row.update(rank=rank,selected=rank<=min(budget,eligible_count))
    return dict(selected=[by_id[r['id']] for r in ranking if r['selected']],ranking=ranking,
        unselected_ids=[r['id'] for r in ranking if not r['selected']],budget=budget,input_count=len(candidates),
        eligible_count=eligible_count,selected_count=min(budget,eligible_count),policy=POLICY,
        policy_sha256=_sha(POLICY),graph_source=graph_source,
        graph_builds=analyzer.graph_builds,graph_cache_hits=analyzer.graph_cache_hits)
