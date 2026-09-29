"""Source-only numeric refinements for oracle-budget shape buckets.

Original-value and coargument order are input relations, not behavioral
equivalence. The optional Python predicate relation has a narrowly supported
local def-use connection; no interprocedural subject dependency is inferred.
"""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation
import importlib.util
from pathlib import Path
import re

from anchor_retrieval.syntax import Source, CALLS, call_parts, child


def numeric_literal(text):
    """Mathematical literal value; excludes bool, strings, calls and NaN."""
    token = text.strip().replace('_', '')
    if re.fullmatch(r'[+-]?0[xX][0-9a-fA-F]+|[+-]?0[bB][01]+|[+-]?0[oO][0-7]+', token):
        return Decimal(int(token, 0))
    if not re.fullmatch(r'[+-]?(?:(?:0|[1-9][0-9]*)(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?', token):
        return None
    try:
        value = Decimal(token)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def order(a, b):
    return (a > b) - (a < b)


def span(source, node):
    return dict(path=source.path, start_byte=node.start_byte, end_byte=node.end_byte,
                line=node.start_point.row+1, end_line=node.end_point.row+1)


def cover(source, start, end):
    if end <= start:
        return None
    node=source.root.named_descendant_for_byte_range(start,end-1)
    return node if node.start_byte==start and node.end_byte==end else None


def numeric_node(node):
    kinds={'integer','float','number','int_literal','float_literal'}
    return node.type in kinds or (node.type in {'unary_operator','unary_expression'}
        and len(node.named_children)==1 and node.named_children[0].type in kinds)


def _argument_value(node):
    return child(node,'value') if node.type in {'keyword_argument','pair'} else node


def coargument_relations(source, node, old, new, replacements):
    call=node.parent
    while call is not None and call.type not in CALLS:
        if call.type.endswith('statement') or call.type in {'assignment','variable_declarator'}:
            return []
        call=call.parent
    if call is None:
        return []
    _,args=call_parts(call)
    owner=next((i for i,arg in enumerate(args) if arg.start_byte<=node.start_byte and node.end_byte<=arg.end_byte),None)
    if owner is None:
        return []
    rows=[]
    for i,arg in enumerate(args):
        if i==owner:
            continue
        value=_argument_value(arg)
        if value is None:
            continue
        other_old=numeric_literal(source.text(value))
        if other_old is None:
            continue
        other_new=replacements.get((source.path,value.start_byte,value.end_byte),other_old)
        if other_new is None:
            continue
        rows.append(dict(kind='numeric_coargument_order', origin='input_syntax_only',
            signature=dict(argument_slot=owner, other_slot=i, before=order(old,other_old), after=order(new,other_new)),
            call_span=span(source,call), other_span=span(source,value),
            other_before=str(other_old), other_after=str(other_new)))
    return rows


def python_local_predicates(source, start, end, old, new, replacements, ast_cache):
    """Direct local numeric assignment -> later direct comparison operand.

    No CFG joins, closure writes, factories, property calls, returned objects or
    actual/formal interprocedural propagation. Reassignment stops the scan.
    """
    if source.path not in ast_cache:
        try:
            tree=ast.parse(source.code)
        except SyntaxError:
            ast_cache[source.path]=None
        else:
            offsets=[0]
            for line in source.code.splitlines(keepends=True):
                offsets.append(offsets[-1]+len(line.encode()))
            ast_cache[source.path]=(tree,offsets)
    cached=ast_cache[source.path]
    if cached is None:
        return []
    tree,offsets=cached
    def ast_span(node):
        return dict(path=source.path, line=node.lineno,end_line=node.end_lineno,
                    start_byte=offsets[node.lineno-1]+node.col_offset,
                    end_byte=offsets[node.end_lineno-1]+node.end_col_offset)
    def bytes_of(node):
        p=ast_span(node)
        return source.data[p['start_byte']:p['end_byte']].decode()
    matches=[]
    for function in ast.walk(tree):
        if not isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)):
            continue
        for pos,statement in enumerate(function.body):
            targets=statement.targets if isinstance(statement,ast.Assign) else [statement.target] if isinstance(statement,ast.AnnAssign) else []
            if len(targets)!=1 or not isinstance(targets[0],ast.Name) or statement.value is None:
                continue
            p=ast_span(statement.value)
            if (p['start_byte'],p['end_byte'])!=(start,end):
                continue
            name=targets[0].id
            if any(isinstance(n,(ast.Global,ast.Nonlocal)) and name in n.names for n in ast.walk(function)):
                return []
            for later in function.body[pos+1:]:
                if isinstance(later,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                    continue
                if any(isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store) and n.id==name for n in ast.walk(later)):
                    break
                for compare in ast.walk(later):
                    if not isinstance(compare,ast.Compare) or len(compare.ops)!=1:
                        continue
                    left,right=compare.left,compare.comparators[0]
                    if isinstance(left,ast.Name) and left.id==name:
                        read,other,side=left,right,'left'
                    elif isinstance(right,ast.Name) and right.id==name:
                        read,other,side=right,left,'right'
                    else:
                        continue
                    bound_old=numeric_literal(bytes_of(other))
                    if bound_old is None:
                        continue
                    p=ast_span(other)
                    bound_new=replacements.get((source.path,p['start_byte'],p['end_byte']),bound_old)
                    if bound_new is None:
                        continue
                    matches.append(dict(kind='local_assignment_comparison_order',origin='local_test_def_use',
                        signature=dict(comparison_ordinal=len(matches), operand=side, operator=type(compare.ops[0]).__name__,
                                       before=order(old,bound_old),after=order(new,bound_new)),
                        binding=name,write_span=ast_span(statement), read_span=ast_span(read),
                        comparison_span=ast_span(compare),bound_span=p,
                        bound_before=str(bound_old),bound_after=str(bound_new)))
    return matches


def candidate_relations(corpus,candidate,source_cache=None,ast_cache=None):
    source_cache={} if source_cache is None else source_cache
    ast_cache={} if ast_cache is None else ast_cache
    edits=sorted(candidate.get('edits',[]),key=lambda e:(e['span']['path'],e['span']['start_byte'],e['span']['end_byte']))
    replacements={(e['span']['path'],e['span']['start_byte'],e['span']['end_byte']):numeric_literal(e['after']) for e in edits}
    result=[]
    for index,edit in enumerate(edits):
        if edit.get('role','').startswith('semantic_'):
            continue
        old,new=numeric_literal(edit['before']),numeric_literal(edit['after'])
        if old is None or new is None:
            continue
        p=edit['span'];path=p['path']
        if path not in source_cache:
            source_cache[path]=Source(path,corpus['sources'][path]['code'],corpus['language'])
        source=source_cache[path]
        if source.data[p['start_byte']:p['end_byte']].decode()!=edit['before'] or source.root.has_error:
            continue
        node=cover(source,p['start_byte'],p['end_byte'])
        if node is None or not numeric_node(node):
            continue
        context=coargument_relations(source,node,old,new,replacements)
        if corpus['language']=='python':
            context+=python_local_predicates(source,p['start_byte'],p['end_byte'],old,new,replacements,ast_cache)
        result.append(dict(edit_index=index,edit_span=p,before=str(old),after=str(new),
                           delta_order=order(new,old),delta_origin='input_change_only',context=context))
    return result


def refine_selections(corpus,candidates,selector_path,budget=16):
    """Isolate unchanged scheduling code; only replace its shape function."""
    spec=importlib.util.spec_from_file_location('_isolated_numeric_selector',selector_path)
    scheduler=importlib.util.module_from_spec(spec);spec.loader.exec_module(scheduler)
    baseline=scheduler.select(corpus,candidates,budget)
    by_id={r['id']:r for r in baseline['ranking']}
    sources,asts={},{}
    evidence={c['id']:candidate_relations(corpus,c,sources,asts) for c in candidates}
    selections={'baseline':baseline}
    for mode in ('delta','context'):
        def refined_shape(unused_corpus,candidate,unused_cache):
            record=by_id[candidate['id']]
            signature=[]
            for row in evidence[candidate['id']]:
                item=dict(edit_index=row['edit_index'],delta_order=row['delta_order'])
                if mode=='context':
                    item['context']=[dict(kind=r['kind'],signature=r['signature']) for r in row['context']]
                signature.append(item)
            return dict(base=record['shape'],numeric_relations=signature),record['normalization_status']
        scheduler._shape=refined_shape
        selected=scheduler.select(corpus,candidates,budget)
        selected['refinement']=mode
        selections[mode]=selected
    return dict(selections=selections,evidence=evidence,
                limits='Literal direction/coarguments are input syntax. Local Python predicates have a restricted local test def-use link; no subject guard, dynamic behavior, oracle validity or compilation is proved.')
