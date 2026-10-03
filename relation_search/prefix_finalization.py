"""Retain explicit source finalizers when constructing a shorter test.

This is a bounded construction heuristic, not a proof of resource safety.
Recognize zero-argument Close/close calls and direct os.remove/os.unlink calls,
including a Go testify NoError adapter. Copy the original complete statement
only when its resource has an unconditional binding before the cut and is not
rebound later. Unknown lifecycle protocols still require full-test review.
"""
from __future__ import annotations

import hashlib
import json

from anchor_retrieval.syntax import Source,child,call_parts,attr_parts,CALLS,ATTRS
from relation_search import oracle,test_prefix_projection


VERSION='source-finalizer-retention.v1'


def _single(node):
    while node is not None and node.type in {'expression_statement','parenthesized_expression','expression_list'} and len(node.named_children)==1:
        node=node.named_children[0]
    return node


def _chain(source,node):
    if node is None:return None
    if node.type in {'identifier','field_identifier'}:return [source.text(node)]
    if node.type in ATTRS:
        owner,name=attr_parts(node);prefix=_chain(source,owner)
        return prefix+[source.text(name)] if prefix is not None else None
    return None


def _finalizer(source,statement):
    node=_single(statement)
    if node is None or node.type not in CALLS:return None
    fn,args=call_parts(node);parts=_chain(source,fn)
    if parts and len(parts)==2 and parts[1]=='NoError' and len(args)==2:
        binding=source.imports.get(parts[0])
        if binding and binding[0] in {'github.com/stretchr/testify/require','github.com/stretchr/testify/assert'}:
            node=_single(args[1])
            if node is None or node.type not in CALLS:return None
            fn,args=call_parts(node);parts=_chain(source,fn)
    method='Close' if source.language=='go' else 'close'
    if parts and len(parts)==2 and parts[1]==method and not args:
        return dict(resource=parts[0],callee='.'.join(parts),basis='source_zero_argument_close_call')
    if source.language=='python' and parts and len(args)==1 and args[0].type=='identifier':
        imported=source.imports.get(parts[0]);canonical=None
        if imported:
            module,symbol=imported;canonical='.'.join([module]+([symbol] if symbol else [])+parts[1:])
        if canonical in {'os.remove','os.unlink'}:
            return dict(resource=source.text(args[0]),callee=canonical,basis='source_stdlib_path_removal')
    return None


def _root_bindings(source,statements):
    """Only direct assignments in the test's top-level statement sequence."""
    rows=[]
    for statement in statements:
        node=_single(statement)
        if node.type not in {'assignment','annotated_assignment','augmented_assignment','short_var_declaration','assignment_statement'}:continue
        left=child(node,'left','name')
        if left is None:continue
        names=left.named_children if left.type in {'expression_list','pattern_list','tuple_pattern'} else [left]
        for name in names:
            if name.type=='identifier':rows.append(dict(name=source.text(name),at=statement.end_byte,kind=node.type))
    return rows


def construct(corpus,frontend,candidate,*,limit=32):
    effective=oracle.program_candidate(candidate)
    result=test_prefix_projection.construct(corpus,frontend,candidate,limit=limit)
    language=corpus['language']
    if language not in {'python','go'}:
        return dict(result,finalization=dict(version=VERSION,status='language_not_supported',retained_statements=0))
    owner=corpus['tests'][candidate['base_test_id']]['span'];header='package prefix\n' if language=='go' else ''
    original=oracle.text(corpus,owner);source=Source(owner['path'],header+original,language)
    # Standalone parsing does not include file imports. Use the original file's
    # resolver for standard assertion and filesystem adapters.
    source.imports.update(Source(owner['path'],corpus['sources'][owner['path']]['code'],language).imports)
    body=test_prefix_projection._body(source)
    if body is None:return dict(result,finalization=dict(version=VERSION,status='no_body',retained_statements=0))
    statements=[n for n in body.named_children if n.type!='comment']
    if language=='go' and len(statements)==1 and statements[0].type=='statement_list':
        statements=[n for n in statements[0].named_children if n.type!='comment']
    offset=owner['start_byte']-len(header.encode());bindings=_root_bindings(source,statements)
    finalizers=[(statement,row) for statement in statements if (row:=_finalizer(source,statement))]
    kept=[];refused=[];retained_count=0
    for program in result['candidates']:
        continuation=next(e for e in program['edits'] if e.get('role')=='projected_continuation')
        cut=continuation['span']['start_byte']-offset;copies=[];unknown=None
        for statement,row in finalizers:
            if statement.start_byte<cut:continue
            declarations=[b for b in bindings if b['name']==row['resource'] and b['at']<=statement.start_byte]
            earlier=[b for b in declarations if b['at']<=cut]
            if not earlier:continue  # resource setup itself was outside this prefix
            if any(b['at']>cut for b in declarations):
                unknown=dict(reason='resource_rebound_in_removed_suffix',resource=row['resource']);break
            begin,end=statement.start_byte+offset,statement.end_byte+offset
            edits=[e for e in effective['edits'] if e['span']['path']==owner['path']
                   and e['span']['start_byte']<end and begin<e['span']['end_byte']]
            if any(e['span']['start_byte']<begin or end<e['span']['end_byte'] for e in edits):
                unknown=dict(reason='edit_crosses_finalizer_statement',resource=row['resource']);break
            statement_code=source.text(statement).encode()
            for edit in sorted(edits,key=lambda e:e['span']['start_byte'],reverse=True):
                a,b=edit['span']['start_byte']-begin,edit['span']['end_byte']-begin
                if statement_code[a:b].decode()!=edit['before']:raise ValueError('Finalizer edit source mismatch')
                statement_code=statement_code[:a]+edit['after'].encode()+statement_code[b:]
            line_start=source.data.rfind(b'\n',0,statement.start_byte)+1
            indent=source.data[line_start:statement.start_byte].decode()
            if indent.strip():indent='\t' if language=='go' else '    '
            copies.append(dict(**row,code=indent+statement_code.decode(),retained_expected_edits=len(edits),
                source_span=dict(path=owner['path'],start_byte=statement.start_byte+offset,end_byte=statement.end_byte+offset)))
        if unknown:
            refused.append(dict(parent_prefix=program['id'],cut=continuation['span'],**unknown));continue
        if copies:
            continuation['after']='\n'+'\n'.join(row['code'] for row in copies)+'\n'
            rendered=oracle.preview(corpus,program)
            if Source(owner['path'],header+rendered,language).root.has_error:
                refused.append(dict(parent_prefix=program['id'],reason='invalid_finalized_prefix_syntax'));continue
            previous=program['id'];program['id']='finalized_'+hashlib.sha256(json.dumps(program['edits'],sort_keys=True).encode()).hexdigest()[:24]
            program['prefix_finalization']=dict(version=VERSION,parent_prefix=previous,retained=copies,
                semantic_validity='unconfirmed',limitation='Name-based source finalizer recognition does not prove a lifecycle protocol. Full test review remains mandatory.')
            retained_count+=len(copies)
        kept.append(program)
    return dict(result,candidates=kept,finalization=dict(version=VERSION,status='constructed',
        retained_statements=retained_count,refused_prefixes=refused,
        original_finalizers=[dict(**row,source=source.text(statement)) for statement,row in finalizers]))
