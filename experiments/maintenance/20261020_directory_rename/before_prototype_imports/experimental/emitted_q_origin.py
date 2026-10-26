"""Exact emitted-clone provenance for assertion and allocation AST spans.

Only source boundaries preserved by recorded byte edits, or an entire AST node
replaced at those exact boundaries, are mapped. New nodes inside replacements
have no claimed source q. Names, assertion text similarity and target labels are
never used to choose an origin. Exact clone bytes must match the emitted file.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json

from experimental.assertion_write_origin import Module
from generic_composition.emitter import _clone, _source, _unit_node, _rename


def key(span):
    return span['path'], span['start_byte'], span['end_byte']


def _code(sources, path):
    row = sources[path]
    return row['code'] if isinstance(row, dict) else row


def clone_mapping(corpus, emitted_sources, item, candidate=None):
    """Return exact source/edit segments for one uniquely located emitted clone."""
    source = _source(corpus, item['path'])
    test = corpus['tests'][item['base_test_id']]
    edits = candidate.get('edits', []) if candidate else []
    clone = _clone(source, test, item['test_name'], edits)
    needle = clone['text'].encode()
    data = _code(emitted_sources, item['path']).encode()
    start = data.find(needle)
    if start < 0 or data.find(needle, start+1) >= 0:
        raise ValueError('emitted_clone_not_uniquely_equal_to_recorded_edits')
    span = test['span']
    first_line = source.data.rfind(b'\n', 0, span['start_byte'])+1
    indent = source.data[first_line:span['start_byte']]
    indent = indent[:len(indent)-len(indent.lstrip(b' \t'))]
    cursor = start+2+len(indent)
    operations = [(edit['span']['start_byte'], edit['span']['end_byte'], edit['after'],
                   edit.get('role', 'input')) for edit in edits]
    a,b,replacement = _rename(source,_unit_node(source,test),item['test_name'])
    operations.append((a,b,replacement,'test_registration_name'))
    operations.sort(key=lambda row:(row[0],row[1]))
    old_cursor, segments = span['start_byte'], []
    for a,b,text,role in [*operations, (span['end_byte'],span['end_byte'],'','end')]:
        if a>old_cursor:
            count=a-old_cursor
            segments.append(dict(emitted_start=cursor,emitted_end=cursor+count,
                source_start=old_cursor,source_end=a,kind='unchanged'))
            cursor+=count
        count=len(text.encode())
        if count:
            segments.append(dict(emitted_start=cursor,emitted_end=cursor+count,
                source_start=a,source_end=b,kind='replacement',role=role))
            cursor+=count
        old_cursor=b
    module=Module(item['path'],source.code,ast.parse(source.code))
    nodes={key(module.span(node)):node for node in ast.walk(module.tree)
           if isinstance(node,(ast.Assert,ast.Call))}
    return dict(path=item['path'],base_test_id=item['base_test_id'],test_name=item['test_name'],
        emitted_start=start,emitted_end=start+len(needle),segments=segments,
        source_nodes=nodes,module=module,edits=edits,
        source_sha256=hashlib.sha256(source.data).hexdigest(),
        emitted_sha256=hashlib.sha256(data).hexdigest())


def map_span(mapping, span, expected_type):
    if span['path']!=mapping['path']:
        return None
    a,b=span['start_byte'],span['end_byte']
    starts,ends=[],[]
    for part in mapping['segments']:
        left,right=part['emitted_start'],part['emitted_end']
        if left<=a<right:
            if part['kind']=='unchanged':
                starts.append(part['source_start']+a-left)
            elif a==left:
                starts.append(part['source_start'])
        if left<b<=right:
            if part['kind']=='unchanged':
                ends.append(part['source_start']+b-left)
            elif b==right:
                ends.append(part['source_end'])
    if len(starts)!=1 or len(ends)!=1:
        return None
    node=mapping['source_nodes'].get((span['path'],starts[0],ends[0]))
    if not isinstance(node,expected_type):
        return None
    source_span=mapping['module'].span(node)
    touching=[edit for edit in mapping['edits'] if
              edit['span']['start_byte']<source_span['end_byte'] and
              source_span['start_byte']<edit['span']['end_byte']]
    return dict(span=source_span,source_sha256=mapping['source_sha256'],
                source_node_edited=bool(touching),
                edit_roles=sorted({edit.get('role','input') for edit in touching}))


def bind_plan_origins(plan, corpus, emitted_sources, items, candidates):
    candidates={row['id']:row for row in candidates}
    maps, failures = {}, []
    for item in items:
        identity=(item['path'],item['test_name'])
        candidate=candidates.get(item.get('candidate_id'))
        if item.get('candidate_id') and candidate is None:
            failures.append(dict(test_name=item['test_name'],reason='candidate_edit_record_missing'))
            continue
        try:
            maps[identity]=clone_mapping(corpus,emitted_sources,item,candidate)
        except (ValueError,KeyError) as error:
            failures.append(dict(test_name=item['test_name'],reason=str(error)))
    result=deepcopy(plan)
    result['queries']=[]
    audits=[]
    for query in plan['queries']:
        q=query['q_span']
        owners=[mapping for mapping in maps.values() if mapping['path']==q['path']
                and mapping['emitted_start']<=q['start_byte']
                and q['end_byte']<=mapping['emitted_end']]
        mapped_q=map_span(owners[0],q,ast.Assert) if len(owners)==1 else None
        allocation=map_span(owners[0],query['allocation_span'],ast.Call) if len(owners)==1 else None
        relevant=[site for site in plan['writes'] if site['class_id']==query['class_id']
                  and site['storage_field']==query['storage_field']]
        writers_unchanged=all(site['writer_span']['path'] in corpus['sources'] and
            _code(emitted_sources,site['writer_span']['path'])==_code(corpus['sources'],site['writer_span']['path'])
            for site in relevant)
        reason=(None if mapped_q and allocation and writers_unchanged else
                'q_byte_edit_origin_unresolved' if not mapped_q else
                'allocation_byte_edit_origin_unresolved' if not allocation else
                'writer_source_changed_outside_known_clone')
        audit=dict(emitted_q=q,emitted_allocation=query['allocation_span'],
            status='mapped' if reason is None else 'unmapped',reason=reason,
            source_q=mapped_q,source_allocation=allocation,
            exact_clone_verified=len(owners)==1,writers_source_unchanged=writers_unchanged)
        audits.append(audit)
        if reason is None:
            result['queries'].append({**query,'source_q_span':mapped_q['span'],
                'source_q_sha256':mapped_q['source_sha256'],
                'source_allocation_span':allocation['span'],
                'source_allocation_sha256':allocation['source_sha256'],
                'source_assertion_edited':mapped_q['source_node_edited'],
                'source_assertion_edit_roles':mapped_q['edit_roles']})
    active={(q['class_id'],q['storage_field']) for q in result['queries']}
    result['writes']=[{**site,'source_writer_span':site['writer_span'],
        'source_writer_sha256':hashlib.sha256(_code(corpus['sources'],site['writer_span']['path']).encode()).hexdigest()}
        for site in plan['writes'] if (site['class_id'],site['storage_field']) in active]
    origins={}
    for q in result['queries']:
        row={name:q[name] for name in ('class_id','allocation_span','source_allocation_span','source_allocation_sha256')}
        origins[json.dumps(row,sort_keys=True)]=row
    result['allocations']=list(origins.values())
    result['classes']=[row for row in plan['classes'] if any(pair[0]==row['class_id'] for pair in active)]
    result['source_q_mapping']=dict(policy='exact_clone_byte_edit_boundaries_v1',
        queries_before=len(plan['queries']),queries_mapped=len(result['queries']),
        queries_excluded=len(plan['queries'])-len(result['queries']),
        clone_failures=failures,queries=audits)
    return result
