"""Project type-invalid pure observations out of a fixed composed test.

Only standalone standard equality assertions with call-free observed/expected
expressions are eligible. Input/action edits cannot be removed. Every compiler
error must be accounted for, and a nonconstant observation must remain. This is
a new weaker test, not a proof that dropping an observation preserves behavior:
property getters and dynamic assertion bindings require whole-test review.
"""
from __future__ import annotations

import copy
import hashlib
import json

from anchor_retrieval.syntax import Source,child,walk
from experimental import assertion_operand_guard as guard
from relation_search import oracle
from relation_search.candidate_edit_transport import rewrite_view


VERSION='type-directed-pure-observation-projection.v3'


def _byte(text,utf16_offset):
    return len(text.encode('utf-16-le')[:2*utf16_offset].decode('utf-16-le').encode())


def pure_reference(source,node):
    if node.type in {'identifier','number','string','true','false','null'}:return True
    if node.type=='member_expression':
        obj,prop=child(node,'object'),child(node,'property')
        return obj is not None and prop is not None and prop.type=='property_identifier' and pure_reference(source,obj)
    if node.type=='subscript_expression':
        obj,index=child(node,'object'),child(node,'index')
        return (obj is not None and index is not None and index.type in {'number','string'}
                and pure_reference(source,obj))
    return False


def parts(code):
    try:
        source=Source('assertion.ts',code,'typescript');statement,observed,expected=guard._ts_parts(source)
        nodes=list(walk(statement))
        # Only expect(...) and its matcher may be explicit calls. Diagnostic
        # arguments also execute, so they cannot hide an additional action.
        if sum(node.type=='call_expression' for node in nodes)!=2:return None
        if any(node.type in {'new_expression','assignment_expression','augmented_assignment_expression',
                             'update_expression','await_expression','yield_expression'} for node in nodes):return None
        if not pure_reference(source,observed):return None
        if not (pure_reference(source,expected) or guard._closed_ts(source,expected)):return None
        if observed.type in {'number','string','true','false','null'}:return None
        return dict(observed=source.text(observed),expected=source.text(expected))
    except (ValueError,TypeError,AttributeError,IndexError):return None


def assertion_key(code):
    # The frontend records the assertion call. The compiler location expands to
    # its expression statement, which can also contain a trailing semicolon.
    return code.strip().removesuffix(';').rstrip()


def project(corpus,frontend,candidate,report,emitted_source):
    def stop(reason):return dict(status='not_projected',candidate=None,reason=reason)
    if corpus['language']!='typescript':return stop('unsupported_language')
    if report.get('status')!='compiler_completed':return stop('compiler_unavailable')
    after=next((r for r in report['phases'] if r['role']=='generated'),None)
    if after is None or hashlib.sha256(emitted_source.encode()).hexdigest()!=after['source_sha256']:
        return stop('compiler_source_mismatch')
    if report['configuration']['parse_errors'] or after['options_diagnostics']:
        return stop('compiler_configuration_errors')
    errors=[row for row in report['new_diagnostics'] if row['category']=='Error']
    if not errors:return stop('no_new_type_errors')
    source=Source(report['target'],emitted_source,'typescript');statements={}
    for error in errors:
        begin,end=(_byte(emitted_source,error[key]) for key in ('start_utf16','end_utf16'))
        node=source.root.named_descendant_for_byte_range(begin,max(begin,end-1))
        while node is not None and node.type!='expression_statement':node=node.parent
        if node is None:return stop('type_error_outside_standalone_assertion')
        code=source.text(node);shape=parts(code)
        if shape is None:return stop('type_error_in_action_or_effectful_observation')
        key=assertion_key(code)
        if key in statements and statements[key]['source_start_byte']!=node.start_byte:
            return stop('ambiguous_repeated_compiler_assertion')
        statements[key]=dict(source_start_byte=node.start_byte,source_end_byte=node.end_byte,
                                    expression=shape,diagnostics=[])
    # Gather all diagnostics for every selected statement, preserving receipts.
    for error in errors:
        position=_byte(emitted_source,error['start_utf16'])
        for row in statements.values():
            if row['source_start_byte']<=position<row['source_end_byte']:row['diagnostics'].append(error)
    candidate=rewrite_view(candidate);base=candidate['base_test_id'];matches={};seen=set()
    for observation in frontend.get('observations',[]):
        if observation.get('test_id')!=base or observation.get('kind')!='assertion':continue
        span=observation.get('assertion_span',observation.get('span'))
        if not span:continue
        key=(span['start_byte'],span['end_byte'])
        if key in seen:continue
        seen.add(key);code=oracle.text(corpus,span);data=code.encode();inside=[]
        for edit in candidate['edits']:
            current=edit['span']
            if current['path']!=span['path'] or current['end_byte']<=span['start_byte'] or span['end_byte']<=current['start_byte']:continue
            if not (span['start_byte']<=current['start_byte'] and current['end_byte']<=span['end_byte']):
                return stop('edit_crosses_observation_boundary')
            inside.append(edit)
        for edit in sorted(inside,key=lambda r:r['span']['start_byte'],reverse=True):
            a,b=edit['span']['start_byte']-span['start_byte'],edit['span']['end_byte']-span['start_byte']
            data=data[:a]+edit['after'].encode()+data[b:]
        current=assertion_key(data.decode())
        if current in statements:
            if current in matches:return stop('ambiguous_repeated_observation')
            if any(edit.get('role')!='semantic_expected' for edit in inside):
                return stop('input_or_observer_edit_inside_removed_assertion')
            matches[current]=dict(span=span,before=code,contained_edits=inside)
    if set(matches)!=set(statements):return stop('compiler_assertion_not_mapped_to_source')
    removed=[edit for row in matches.values() for edit in row['contained_edits']]
    revised=copy.deepcopy(candidate);revised['edits']=[edit for edit in revised['edits'] if edit not in removed]
    revised['edits'].extend(dict(span=row['span'],before=row['before'],after='',role='projected_observation') for row in matches.values())
    rendered=oracle.preview(corpus,revised);parsed=Source('projected.ts',rendered,'typescript')
    if parsed.root.has_error:return stop('projection_syntax_error')
    remaining=[]
    for node in walk(parsed.root):
        if node.type!='expression_statement':continue
        try:
            item=Source('observation.ts',parsed.text(node),'typescript');_,observed,_=guard._ts_parts(item)
            if observed.type not in {'number','string','true','false','null'}:remaining.append(item.text(observed))
        except (ValueError,TypeError,AttributeError,IndexError):pass
    if not remaining:return stop('no_remaining_nonconstant_observation')
    if not any(edit.get('role') not in {'semantic_expected','projected_observation'} for edit in revised['edits']):
        return stop('no_remaining_input_composition')
    parent=revised['id'];revised['id']='projection_'+hashlib.sha256(json.dumps(revised['edits'],sort_keys=True).encode()).hexdigest()[:24]
    revised['observer_projection']=dict(version=VERSION,parent=parent,removed=list(statements.values()),
        remaining_observations=remaining,whole_test_review_required=True,compiler_recheck_required=True,
        native_reexecution_required=True,semantic_validity='unconfirmed',
        limitation='Syntactically call-free reads can still involve getters. This is a new weaker test, not an equivalence proof.')
    return dict(status='projected',candidate=revised,removed_assertions=len(matches),remaining_observations=len(remaining))
