"""Source MAY-access summaries for constructive observation-address joins.

Addresses are exactly ``receiver.field`` or ``receiver.field[key]``. Keys are
formal parameters or primitive literals, optionally via straight-line locals.
Reads must occur in a returned expression (or its straight-line local inputs).
Guards are retained, never solved: a missing/incorrect guard can be the defect.
No summary is an oracle or a proof that a store executes, survives, or matters.
"""
from __future__ import annotations

import hashlib
import posixpath

from anchor_retrieval.syntax import ATTRS, FUNCTIONS, Source, attr_parts, child, literal, walk

VERSION = 'source-observation-address-effects.v3'
INDEXES = {'subscript','subscript_expression','index_expression'}
ASSIGNMENTS = {'assignment','augmented_assignment','assignment_statement','short_var_declaration',
               'assignment_expression','augmented_assignment_expression','variable_declarator','var_spec'}
SCOPES = FUNCTIONS | {'func_literal','arrow_function','function_expression','lambda','class_definition','class_declaration'}
CONTROLS = {'if_statement','for_statement','while_statement','for_in_statement','do_statement',
            'try_statement','with_statement','match_statement','switch_statement','expression_switch_statement',
            'type_switch_statement','select_statement','conditional_expression','ternary_expression'}
UNSUPPORTED = {'global_statement','nonlocal_statement','named_expression','await','await_expression',
               'yield','yield_expression','go_statement','defer_statement','goto_statement',
               'try_statement','with_statement','match_statement','type_switch_statement','select_statement',
               'catch_clause','except_clause','import_statement','import_from_statement','delete_statement'}


def _ref(source,node):
    return dict(path=source.path,start_byte=node.start_byte,end_byte=node.end_byte,
                start_line=node.start_point.row+1,end_line=node.end_point.row+1)


def _inside(outer,inner):
    return outer.start_byte <= inner.start_byte and inner.end_byte <= outer.end_byte


def _unwrap(node):
    while node is not None and node.type in {'parenthesized_expression','expression_list'} and len(node.named_children)==1:
        node=node.named_children[0]
    return node


def _targets(node):
    if node is None:
        return []
    if node.type=='identifier':
        return [node]
    if node.type in {'expression_list','pattern_list','tuple_pattern','list_pattern','array_pattern','tuple','list'}:
        return [n for part in node.named_children for n in _targets(part)]
    return []


def _owner(index,unit):
    source=unit.source
    if not unit.owner:
        raise ValueError('method_owner_unavailable')
    if source.language in {'python','typescript'}:
        owner=unit.node.parent
        while owner is not None and owner.type not in {'class_definition','class_declaration'}:
            owner=owner.parent
        if owner is None:
            raise ValueError('class_declaration_unavailable')
        key=(source.language,source.path,owner.start_byte,owner.end_byte,source.text(child(owner,'name')))
        return key,_ref(source,owner)
    package=index.go_packages.get(source.path)
    directory=posixpath.dirname(source.lookup_path)
    choices=[]
    for other in index.sources.values():
        if (other.language!='go' or posixpath.dirname(other.lookup_path)!=directory
                or index.go_packages.get(other.path)!=package):
            continue
        for node in walk(other.root):
            if node.type=='type_spec' and other.text(child(node,'name'))==unit.owner:
                # A type inside a function is not the receiver's package type.
                ancestor=node.parent
                while ancestor is not None and ancestor.type not in SCOPES:
                    ancestor=ancestor.parent
                if ancestor is None:
                    choices.append((other,node))
    if len(choices)!=1:
        raise ValueError('receiver_type_declaration_not_unique')
    other,node=choices[0]
    return ('go',other.path,node.start_byte,node.end_byte,unit.owner),_ref(other,node)


def _receiver(unit):
    if unit.source.language=='python':
        if unit.decorators or not unit.params:
            raise ValueError('decorated_or_parameterless_python_method')
        return unit.params[0]
    if unit.source.language=='typescript':
        # Static methods do not bind the ordinary instance receiver.
        if any(n.type=='static' for n in unit.node.children):
            raise ValueError('static_method_receiver_unavailable')
        return 'this'
    receiver=child(unit.node,'receiver')
    parameters=list(receiver.named_children) if receiver is not None else []
    name=child(parameters[0],'name') if len(parameters)==1 else None
    if name is None:
        raise ValueError('receiver_parameter_unavailable')
    return unit.source.text(name)


def _guards(source,node,body):
    result=[]; cursor=node
    while cursor is not None and cursor!=body:
        parent=cursor.parent
        if parent is not None and parent.type in CONTROLS:
            condition=child(parent,'condition','value')
            row=dict(kind=parent.type,span=_ref(source,parent),feasibility='unproved')
            if condition is not None:
                row['condition_span']=_ref(source,condition)
            alternative=child(parent,'alternative')
            row['branch']='alternative' if alternative is not None and _inside(alternative,node) else 'body_or_consequence'
            result.append(row)
        cursor=parent
    return list(reversed(result))


def summarize_method(index,function_id,*,max_nodes=4000):
    """Summarize one resolved declaration; callers must prove call resolution.

    `owner_key` is a hashable declaration identity. Formal indices refer to
    `unit.params`, matching the existing frontend's parameter indexes.
    """
    result=dict(version=VERSION,function_id=function_id,status='unknown',reads=[],writes=[],unknowns=[],
        receiver_name=None,owner_key=None,explicit_parameters=[],
        interpretation='source_may_access_not_runtime_effect_or_oracle',complete_effect_summary=False)
    try:
        unit=index.units[function_id];source=unit.source;body=unit.body
        result['source_sha256']=hashlib.sha256(source.data).hexdigest()
        result['method_span']=_ref(source,unit.node)
        if source.root.has_error:
            raise ValueError('method_source_parse_error')
        nodes=list(walk(body))
        if len(nodes)>max_nodes:
            raise ValueError('method_node_budget')
        owner_key,owner_span=_owner(index,unit);receiver=_receiver(unit)
        result.update(owner_key=owner_key,owner_span=owner_span,receiver_name=receiver)
        formals={name:i for i,name in enumerate(unit.params) if name!=receiver}
        result['explicit_parameters']=[dict(name=name,parameter_index=position,argument_index=i)
                                       for i,(name,position) in enumerate(formals.items())]
        if any(n.type in SCOPES | UNSUPPORTED for n in nodes if n!=body):
            raise ValueError('nested_scope_or_unsupported_effect_control')
        protected=set(formals)|{receiver}
        for node in nodes:
            targets=[]
            if node.type in ASSIGNMENTS:
                targets=_targets(child(node,'left','name'))
            elif node.type in {'for_statement','for_in_statement','range_clause'}:
                targets=_targets(child(node,'left','name'))
            elif node.type in {'update_expression','inc_statement','dec_statement','delete_statement'}:
                targets=_targets(_unwrap(child(node,'argument','operand') or next(iter(node.named_children),None)))
            if any(source.text(t) in protected for t in targets):
                raise ValueError('receiver_or_formal_rebound')
            if (source.language=='go' and node.type=='unary_expression' and source.text(child(node,'operator'))=='&'
                    and source.text(_unwrap(child(node,'operand'))) in protected):
                raise ValueError('receiver_or_formal_address_escapes')
        controlled=any(n.type in CONTROLS for n in nodes)
        environment={}; seen=set()

        def key_term(node,environment,depth=0):
            node=_unwrap(node)
            if node is None or depth>16:
                return None
            name=source.text(node)
            if node.type=='identifier':
                if name in formals:
                    return dict(kind='formal',name=name,parameter_index=formals[name],
                                argument_index=list(formals).index(name))
                if not controlled and name in environment:
                    value,snapshot=environment[name]
                    return key_term(value,snapshot,depth+1)
                return None
            try:
                value=literal(name)
            except ValueError:
                return None
            if type(value) not in {str,int,float,bool,type(None)}:
                return None
            literal_kind=(name if value is None else 'go_rune' if source.language=='go' and name.startswith("'") else type(value).__name__)
            return dict(kind='literal',literal_kind=literal_kind,text=name,value=value,value_span=_ref(source,node))

        def address(node,environment):
            node=_unwrap(node)
            if node is None:
                return None
            key=None;key_node=None;member=node
            if node.type in INDEXES:
                member=_unwrap(child(node,'value','object','operand'))
                key_node=child(node,'subscript','index')
                key=key_term(key_node,environment)
                if key is None:
                    return None
            if member is None or member.type not in ATTRS:
                return None
            owner,field=attr_parts(member);owner=_unwrap(owner)
            if owner is None or source.text(owner)!=receiver or owner.type not in {'identifier','this'}:
                return None
            if field is None or field.type not in {'identifier','field_identifier','property_identifier'}:
                return None
            return dict(owner_key=owner_key,field=source.text(field),key=key,address_span=_ref(source,node),
                        key_span=_ref(source,key_node) if key_node is not None else None)

        def record(kind,node,statement,environment):
            row=address(node,environment)
            if row is None:
                return False
            signature=(kind,node.start_byte,node.end_byte,statement.start_byte)
            if signature not in seen:
                seen.add(signature)
                row.update(kind=kind,span=_ref(source,node),statement_span=_ref(source,statement),
                    function_id=function_id,receiver_name=receiver,source_sha256=result['source_sha256'],
                    guards=_guards(source,node,body),access_status='may_source_access',
                    return_link='returned_expression_may_dependence' if kind=='read' else None,
                    final_store_proved=False)
                result['reads' if kind=='read' else 'writes'].append(row)
            return True

        def reads(node,statement,environment,depth=0):
            if node is None or depth>16:
                return
            node=_unwrap(node)
            if record('read',node,statement,environment):
                return  # Do not turn the base of items[key] into a plain-field read.
            if node.type=='identifier' and not controlled and source.text(node) in environment:
                value,snapshot=environment[source.text(node)]
                reads(value,statement,snapshot,depth+1)
                return
            if node.type in INDEXES:
                # Unsupported computed/indexed address is not a plain-field demand.
                return
            for part in node.named_children:
                reads(part,statement,environment,depth+1)

        listing=next((n for n in body.named_children if n.type=='statement_list'),body)
        if controlled:
            for node in nodes:
                if node.type=='return_statement':
                    for part in node.named_children:
                        reads(part,node,{})
                elif node.type in ASSIGNMENTS:
                    left=_unwrap(child(node,'left','name'))
                    if left is not None:
                        record('write',left,node,{})
        else:
            for statement in listing.named_children:
                if statement.type=='comment':
                    continue
                node=statement
                if node.type=='expression_statement' and len(node.named_children)==1:
                    node=node.named_children[0]
                if node.type=='return_statement':
                    for part in node.named_children:
                        reads(part,node,environment)
                    break  # Lexically later statements cannot supply this method's return.
                assignments=[node] if node.type in ASSIGNMENTS else (
                    [n for n in node.named_children if n.type in ASSIGNMENTS]
                    if node.type in {'lexical_declaration','variable_declaration','var_declaration'} else [])
                for assignment in assignments:
                    left=_unwrap(child(assignment,'left','name'));right=_unwrap(child(assignment,'right','value'))
                    if left is None:
                        continue
                    record('write',left,assignment,environment)
                    targets=_targets(left)
                    if len(targets)==1 and left.type=='identifier' and right is not None:
                        operator=source.text(child(assignment,'operator'))
                        if operator in {'=',':=',''} and 'augmented' not in assignment.type:
                            environment[source.text(left)]=(right,dict(environment))
                        else:
                            environment.pop(source.text(left),None)
                    else:
                        for target in targets:
                            environment.pop(source.text(target),None)
        result['status']='source_summary'
        if controlled:
            result['unknowns'].append(dict(reason='guards_and_loop_iterations_not_solved'))
    except (KeyError,ValueError,TypeError,AttributeError) as error:
        result['unknowns'].append(dict(reason=str(error)))
        result['reads']=[];result['writes']=[]
    return result
