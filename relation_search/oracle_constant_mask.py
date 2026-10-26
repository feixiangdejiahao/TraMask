"""Mask constant locals used only as expected operands or diagnostics.

This edits a model view only. It never changes the executed program. A name
with an input/observed use, more than one definition, or a nonliteral value is
left intact. Unresolved aliasing is not guessed.
"""
from __future__ import annotations

import ast

from anchor_retrieval.syntax import Source,child,walk
from prototypes import assertion_operand_guard as guard


VERSION='constant-oracle-local-mask.v1'


def closed(source,node):
    try:
        if source.language=='python':
            guard._closed_python(ast.parse(source.text(node),mode='eval').body)
            return True
        if source.language=='typescript':return guard._closed_ts(source,node)
        return guard._closed_go(source,node)
    except (ValueError,TypeError,SyntaxError):return False


def diagnostic_ranges(source):
    ranges=[]
    for node in walk(source.root):
        if source.language=='python' and node.type=='assert_statement':
            parts=node.named_children
            if len(parts)>1:ranges.append((parts[1].start_byte,parts[1].end_byte))
        if source.language!='go' or node.type!='call_expression':continue
        function=child(node,'function');arguments=child(node,'arguments')
        if function is None or function.type!='selector_expression' or arguments is None:continue
        method=source.text(child(function,'field'));receiver=source.text(child(function,'operand'))
        args=guard._nodes(arguments)
        if receiver in {'require','assert'}:
            start=3 if method in {'Equal','NotEqual'} else 2
            if method in {'Equal','NotEqual','Error','NoError','True','False','Nil','NotNil','Empty','NotEmpty'}:
                ranges.extend((part.start_byte,part.end_byte) for part in args[start:])
        elif method in {'Errorf','Fatalf','Error','Fatal','Log','Logf'}:
            # Only testing.T-shaped diagnostics inside an assertion failure
            # branch are accepted. Other source calls remain semantically live.
            parent=node.parent
            inside=False
            while parent is not None:
                if parent.type=='if_statement':inside=True;break
                if parent.type in {'function_declaration','function_literal'}:break
                parent=parent.parent
            if receiver=='t' and inside:ranges.extend((part.start_byte,part.end_byte) for part in args)
    return ranges


def collect(code,language,expected_ranges):
    prefix='package mask\n' if language=='go' else ''
    shift=len(prefix.encode());source=Source('masked-test',prefix+code,language)
    if source.root.has_error:return []
    allowed=[(a+shift,b+shift) for a,b in expected_ranges]+diagnostic_ranges(source)
    definitions={};identifiers={}
    for node in walk(source.root):
        if node.type=='identifier':identifiers.setdefault(source.text(node),[]).append(node)
        left=right=None
        if node.type=='assignment' and language=='python':left,right=child(node,'left'),child(node,'right')
        elif node.type in {'short_var_declaration','assignment_statement'} and language=='go':
            left,right=child(node,'left'),child(node,'right')
            if left is not None and right is not None and len(left.named_children)==len(right.named_children)==1:
                left,right=left.named_children[0],right.named_children[0]
            else:left=right=None
        elif node.type=='variable_declarator' and language=='typescript':left,right=child(node,'name'),child(node,'value')
        if left is not None and left.type=='identifier' and right is not None:
            definitions.setdefault(source.text(left),[]).append((left,right))
    records=[]
    for name,values in sorted(definitions.items()):
        if len(values)!=1:continue
        declaration,value=values[0]
        if not closed(source,value):continue
        uses=[node for node in identifiers.get(name,[]) if node.id!=declaration.id]
        if not any(any(a+shift<=node.start_byte and node.end_byte<=b+shift
                       for a,b in expected_ranges) for node in uses):continue
        if any(not any(a<=node.start_byte and node.end_byte<=b for a,b in allowed) for node in uses):continue
        records.append(dict(name=name,start=value.start_byte-shift,end=value.end_byte-shift,
            declaration_start=declaration.start_byte-shift,
            reason='single_literal_definition_all_reads_in_expected_operands_or_diagnostics'))
    return records
