"""Construct bounded complete test prefixes at original observation boundaries.

This changes a test intentionally. It is not an equivalence proof. Every input
edit is retained; only later oracle edits and whole trailing statements can be
removed. A retained source observation and a syntactically complete body are
required. Original lexical resource scopes are never split. Explicit suffix
cleanup can be removed, so probes require isolated environments and a fresh
whole-program validity review before they can become detector alerts.
"""
from __future__ import annotations

import copy
import hashlib
import json

from anchor_retrieval.syntax import Source,child,walk
from relation_search import oracle
from relation_search.candidate_edit_transport import rewrite_view


VERSION='source-observation-prefix-projection.v2'
ORACLE_ROLES={'semantic_expected','projected_observation','projected_continuation'}


def _body(source):
    if source.language in {'python','go'}:
        roots=[n for n in source.root.named_children if n.type in {'function_definition','function_declaration','decorated_definition'}]
        if len(roots)!=1:return None
        node=roots[0]
        if node.type=='decorated_definition':node=child(node,'definition')
        return child(node,'body') if node is not None else None
    functions=[node for node in walk(source.root) if node.type in {'arrow_function','function_expression'} and child(node,'body') is not None]
    if not functions:return None
    def depth(node):
        level=0
        while node.parent is not None:level+=1;node=node.parent
        return level
    shallow=min(depth(n) for n in functions);roots=[n for n in functions if depth(n)==shallow]
    if len(roots)!=1:return None
    body=child(roots[0],'body')
    return body if body.type=='statement_block' else None


def construct(corpus,frontend,candidate,*,limit=32):
    if type(limit) is not int or limit<1:raise ValueError('A positive finite prefix limit is required')
    candidate=rewrite_view(candidate);owner=corpus['tests'][candidate['base_test_id']]['span']
    language=corpus['language'];header='package prefix\n' if language=='go' else ''
    original=oracle.text(corpus,owner);source=Source(owner['path'],header+original,language)
    body=_body(source)
    if source.root.has_error or body is None:return dict(version=VERSION,candidates=[],reason='unsupported_test_body')
    statements=[n for n in body.named_children if n.type!='comment']
    if language=='go' and len(statements)==1 and statements[0].type=='statement_list':
        statements=[n for n in statements[0].named_children if n.type!='comment']
    offset=owner['start_byte']-len(header.encode())
    suffix_end=body.end_byte-(1 if language in {'go','typescript'} else 0)+offset
    observations=[]
    for row in frontend.get('observations',[]):
        if row.get('test_id')!=candidate['base_test_id']:continue
        span=row.get('assertion_span',row.get('span'))
        if span and span['path']==owner['path']:observations.append(span)
    if not observations:return dict(version=VERSION,candidates=[],reason='no_source_observation')
    results=[];skipped=[]
    for statement in statements:
        cut=statement.end_byte+offset
        contained=[s for s in observations if statement.start_byte+offset<=s['start_byte'] and s['end_byte']<=cut]
        if not contained or cut>=suffix_end:continue
        suffix=dict(path=owner['path'],start_byte=cut,end_byte=suffix_end)
        before=oracle.text(corpus,suffix)
        if not before.strip():continue
        removed=[];conflict=None
        for edit in candidate['edits']:
            span=edit['span']
            if span['path']!=suffix['path'] or span['end_byte']<=cut or suffix_end<=span['start_byte']:continue
            if not (cut<=span['start_byte'] and span['end_byte']<=suffix_end):conflict='edit_crosses_prefix_boundary';break
            if edit.get('role','input') not in ORACLE_ROLES:conflict='would_remove_input_edit';break
            removed.append(edit)
        if conflict:
            skipped.append(dict(cut_byte=cut,reason=conflict));continue
        # At least one observed source site must remain outside a deletion.
        retained=[span for span in observations if span['end_byte']<=cut and not any(
            edit['span']['path']==span['path'] and edit['span']['start_byte']<=span['start_byte']
            and span['end_byte']<=edit['span']['end_byte'] and not edit['after'].strip()
            for edit in candidate['edits'])]
        if not retained:continue
        result=copy.deepcopy(candidate);result['edits']=[e for e in result['edits'] if e not in removed]
        # Keep a newline before the closing brace. Python closes its block by
        # indentation; preserving a terminal newline also keeps trailing tokens
        # from joining a retained statement during file materialization.
        result['edits'].append(dict(span=suffix,before=before,after='\n',role='projected_continuation'))
        rendered=oracle.preview(corpus,result)
        if Source(owner['path'],header+rendered,language).root.has_error:
            skipped.append(dict(cut_byte=cut,reason='invalid_projected_syntax'));continue
        inputs=[e for e in candidate['edits'] if e.get('role','input') not in ORACLE_ROLES]
        if not inputs:continue
        if not all(e in result['edits'] for e in inputs):raise AssertionError('Input edit removed')
        result['id']='prefix_'+hashlib.sha256(json.dumps(result['edits'],sort_keys=True).encode()).hexdigest()[:24]
        result['prefix_projection']=dict(version=VERSION,parent=candidate['id'],cut=suffix,
            retained_source_observations=len(retained),input_edits_preserved=len(inputs),
            removed_oracle_edits=len(removed),whole_test_review_required=True,native_reexecution_required=True,
            semantic_validity='unconfirmed',limitation='A new weaker test. Explicit suffix cleanup can be removed; execute only in an isolated environment. Lexical scopes are preserved.')
        results.append(result)
        if len(results)>=limit:break
    return dict(version=VERSION,candidates=results,skipped=skipped,limit=limit,
                selection='earliest_complete_root_statement_with_source_observation_after_all_retained_input_edits')
