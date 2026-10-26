"""Render existing source facts to help a model trace a candidate's dependencies.

The edges are original-source may evidence, not a modified-program slice or
oracle proof. This module does not select expectations, dispatch or rank tests.
"""
from __future__ import annotations

import json

from prototypes.singleton_oracle_slots import changed_call_context, source_contexts
from relation_search.oracle import text


def overlaps(left,right):
    if not left or not right or left['path']!=right['path']:
        return False
    if left['start_byte']==left['end_byte']:
        return right['start_byte']<=left['start_byte']<=right['end_byte']
    return left['start_byte']<right['end_byte'] and right['start_byte']<left['end_byte']


def candidate_evidence(corpus,frontend,candidate):
    """Seed original calls from edited spans/value-use facts, then link their q.

No name matching resolves a new callee. Actual/formal maps refer only to the
original call. The full modified test must accompany these supplementary facts.
    """
    edits=[edit for edit in candidate['edits'] if edit.get('role')!='semantic_expected']
    for edit in edits:
        if text(corpus,edit['span'])!=edit['before']:
            raise ValueError('Input edit does not match original source')
    test_id=candidate['base_test_id']
    calls={row['id']:row for row in frontend.get('calls',[]) if row.get('test_id')==test_id}
    observations={row['id']:row for row in frontend.get('observations',[]) if row.get('test_id')==test_id}
    functions={row['id']:row for row in frontend.get('functions',[])}
    bindings={row['id']:row for row in frontend.get('bindings',[]) if row.get('test_id')==test_id}
    invalidated,_=changed_call_context(corpus,candidate)
    unknowns=list(source_contexts(corpus,frontend,candidate)['missing'])
    seed_edges=[]
    seeds={cid for cid,row in calls.items() if any(overlaps(edit['span'],row['span']) for edit in edits)}
    for value in frontend.get('values',[]):
        if value.get('test_id')!=test_id:
            continue
        for index,edit in enumerate(edits):
            if overlaps(edit['span'],value.get('span')):
                for edge in value.get('input_slots',[])+value.get('argument_slots',[]):
                    if edge['call_id'] in calls:
                        seeds.add(edge['call_id'])
                        seed_edges.append(dict(source='E:'+str(index),target='C:'+edge['call_id'],
                            kind='original_value_use',slot=edge['slot']))
    edited_bindings={bid for bid,row in bindings.items() if any(overlaps(edit['span'],row['span']) for edit in edits)}
    for cid,call in calls.items():
        refs=[call.get('receiver_binding')]+[arg.get('binding') for arg in call.get('arguments',[])]
        if any(ref and {ref.get('binding_id'),ref.get('origin_binding_id')} & edited_bindings for ref in refs):
            seeds.add(cid)
    qids={oid for cid in seeds for oid in calls[cid].get('observation_ids',[]) if oid in observations}
    # Show the edited-input call frontier and every q linked to it. Other
    # producers of those q stay in the required full test; this is not a slice.
    related=set(seeds)
    nodes,edges={},seed_edges
    if not seeds:
        unknowns.append(dict(reason='no_original_call_link_for_edits'))

    def node(identifier,kind,extent,**extra):
        if not extent or extent.get('path') not in corpus['sources']:
            unknowns.append(dict(reason='source_span_unavailable',id=identifier))
            return False
        nodes.setdefault(identifier,dict(id=identifier,kind=kind,span=extent,code=text(corpus,extent),**extra))
        return True

    def local_binding(origin,ref):
        if not ref:
            return
        for key in ['binding_id','origin_binding_id']:
            bid=ref.get(key)
            if bid in bindings and node('B:'+bid,'binding',bindings[bid]['span']):
                edges.append(dict(source=origin,target='B:'+bid,kind='original_local_binding',
                                  binding_role=key,object_identity='unknown',resolution=ref.get('resolution')))

    for index,edit in enumerate(edits):
        node('E:'+str(index),'input_edit',edit['span'],after=edit['after'])
    for qid in sorted(qids):
        row=observations[qid]
        node('Q:'+qid,'observation',row.get('assertion_span') or row.get('span'),
             observed=row.get('observed'),predicate=row.get('predicate'))
    for cid in sorted(related,key=lambda key:(calls[key]['span']['path'],calls[key]['span']['start_byte'])):
        call=calls[cid];identifier='C:'+cid
        node(identifier,'call',call['span'],seed=cid in seeds,role=call.get('role'))
        for qid in sorted(set(call.get('observation_ids',[])) & qids):
            edges.append(dict(source=identifier,target='Q:'+qid,kind='original_static_slice_may_dependence'))
        for index,edit in enumerate(edits):
            if overlaps(edit['span'],call['span']):
                edges.append(dict(source='E:'+str(index),target=identifier,kind='source_span_overlap'))
        extent=call['span'];key=(extent['path'],extent['start_byte'],extent['end_byte'])
        receiver=call.get('receiver_binding')
        receiver_changed=bool(receiver and {receiver.get('binding_id'),receiver.get('origin_binding_id')} & edited_bindings)
        if key in invalidated or receiver_changed:
            unknowns.append(dict(reason='modified_callee_binding_not_reused',call_id=cid,
                                 receiver_definition_edited=receiver_changed))
            continue
        if call.get('receiver'):
            rid='R:'+cid
            if node(rid,'receiver',call['receiver'].get('span')):
                edges.append(dict(source=identifier,target=rid,kind='receiver_expression'))
                local_binding(rid,receiver)
        targets=[row for row in call.get('targets',[]) if row.get('resolved') and row['function_id'] in functions]
        if len(targets)!=1:
            unknowns.append(dict(reason='original_target_unresolved_or_ambiguous',call_id=cid))
            continue
        target=targets[0];function=functions[target['function_id']];fid='F:'+function['id']
        if not node(fid,'declaration',function['span']):
            continue
        edges.append(dict(source=identifier,target=fid,kind='original_source_target',resolution=target['reason']))
        args={row['slot']:row for row in call.get('arguments',[])}
        params={row['index']:row for row in function.get('parameters',[])}
        for binding in call.get('argument_bindings',[]):
            if binding['function_id']!=function['id'] or binding['slot'] not in args or binding['parameter_index'] not in params:
                continue
            if binding['binding_status']!='direct_actual_formal':
                unknowns.append(dict(reason='original_actual_formal_uncertain',call_id=cid,slot=binding['slot']))
                continue
            arg,param=args[binding['slot']],params[binding['parameter_index']]
            aid=f"A:{cid}:{binding['slot']}";pid=f"P:{function['id']}:{binding['parameter_index']}"
            if node(aid,'actual',arg['span']) and node(pid,'formal',param['span']):
                edges.append(dict(source=aid,target=pid,kind='original_actual_formal',call_id=cid,
                                  parameter=param.get('name'),slot=binding['slot']))
                local_binding(aid,arg.get('binding'))
    edges=list({json.dumps(row,sort_keys=True):row for row in edges}.values())
    unknowns=list({json.dumps(row,sort_keys=True):row for row in unknowns}.values())
    return dict(candidate_id=candidate['id'],source_scope='original_source_may_evidence',
        seed_call_ids=sorted(seeds),related_observation_ids=sorted(qids),
        nodes=list(nodes.values()),edges=edges,unknowns=unknowns,
        modified_bindings_recomputed=False,full_modified_test_required=True,
        complete_slice=False,oracle_validity='not_evaluated')


def render_evidence(evidence):
    """Deterministic source excerpts and typed graph edges; no generated prose."""
    lines=['Original-source may evidence; new bindings and runtime object identity are not proved.',
           'Use with the complete modified test and issue contract.']
    # A declaration already contains its formal/actual subexpressions. Keep all
    # node positions and graph edges, but print overlapping source text once.
    owners={}
    maximal=[]
    for row in sorted(evidence['nodes'],key=lambda row:(row['span']['path'],row['span']['start_byte'],-row['span']['end_byte'])):
        span=row['span']
        owner=next((other for other in maximal if other['span']['path']==span['path'] and
                    other['span']['start_byte']<=span['start_byte'] and span['end_byte']<=other['span']['end_byte']),None)
        if owner is None:
            maximal.append(row)
            owner=row
        owners[row['id']]=owner['id']
    for row in evidence['nodes']:
        span=row['span']
        lines.append(f"{row['id']} [{row['kind']}] {span['path']}:{span['start_byte']}..{span['end_byte']}")
        lines.append(row['code'] if owners[row['id']]==row['id'] or row['kind']=='input_edit'
                     else 'source excerpt: '+owners[row['id']])
        if row['kind']=='input_edit':
            lines.extend(['=>',row['after']])
    for edge in evidence['edges']:
        suffix=f" parameter={edge['parameter']} slot={edge['slot']}" if edge['kind']=='original_actual_formal' else ''
        if edge['kind']=='original_local_binding':
            suffix=f" role={edge['binding_role']} object_identity=unknown"
        lines.append(f"{edge['source']} --{edge['kind']}--> {edge['target']}{suffix}")
    for row in evidence['unknowns']:
        key=row.get('call_id') or row.get('callee') or row.get('original_callee') or row.get('id') or ''
        lines.append(f"UNKNOWN {row['reason']} {key}")
    return '\n'.join(lines)+'\n'
