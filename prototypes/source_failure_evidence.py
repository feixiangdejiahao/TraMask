"""Finite Go source facts connecting guarded calls to standard testing sinks.

Only lexical may reachability and syntactic formal dependencies are computed.
No function/parameter name identifies an oracle role; diagnostic arguments are
not predicates. An implementation, including a buggy one, is never a contract.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import posixpath

from anchor_retrieval.syntax import Source, attr_parts, call_parts, child, walk
from generic_composition.corpus import span
from relation_search.oracle_evidence import _modified_sources

VERSION = 'source-failure-evidence-v1'
SINK_METHODS = {'Fail', 'FailNow', 'Error', 'Errorf', 'Fatal', 'Fatalf'}
WRITES = {'short_var_declaration', 'assignment_statement', 'var_spec'}


def _id(*values):
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:24]


def _owned(node):
    yield node
    for item in node.named_children:
        if item.type != 'func_literal':
            yield from _owned(item)


def _items(node):
    if node is None:
        return []
    if node.type in {'block', 'statement_list'}:
        return [item for child_node in node.named_children
                for item in (list(child_node.named_children) if child_node.type=='statement_list' else [child_node])
                if item.type!='comment']
    return [] if node.type == 'comment' else [node]


def _list(node):
    return list(node.named_children) if node is not None and node.type == 'expression_list' else [node] if node is not None else []


def _writes(source, node):
    target = child(node, 'left', 'name') if node.type in WRITES else None
    if node.type in {'var_spec','const_spec'}:
        return {source.text(item) for i,item in enumerate(node.named_children)
                if node.field_name_for_named_child(i)=='name' and item.type=='identifier'}
    if node.type in {'type_spec','type_alias'}:
        return {source.text(child(node,'name'))}
    if node.type == 'range_clause':
        target = child(node,'left')
    if node.type in {'inc_statement', 'dec_statement'}:
        target = node.named_children[0] if node.named_children else None
    if node.type == 'type_switch_statement':
        target = child(node, 'alias')
    return {source.text(item) for item in _list(target) if item.type == 'identifier'}


def _parameters(source, node):
    result = []
    for declaration in child(node, 'parameters').named_children:
        if declaration.type == 'comment':
            continue
        names = [item for item in declaration.named_children if item.type == 'identifier']
        kind = child(declaration, 'type')
        if declaration.type not in {'parameter_declaration', 'variadic_parameter_declaration'} or not names or kind is None:
            return result, 'unsupported_parameter_shape'
        aliases = {name for name, imported in source.imports.items() if imported == ('testing', None)}
        # Exact source type, not a same-spelling local T, interface or wrapper.
        pointed = kind.named_children[0] if kind.type == 'pointer_type' and len(kind.named_children) == 1 else None
        testing = pointed is not None and pointed.type == 'qualified_type' and source.text(child(pointed, 'package')) in aliases and source.text(child(pointed, 'name')) == 'T'
        for name in names:
            result.append(dict(index=len(result), name=source.text(name), type=source.text(kind), span=span(source,name),
                variadic=declaration.type=='variadic_parameter_declaration', testing_receiver=bool(testing)))
    return result, None


def _deps(source, node, env):
    if node is None or node.type == 'func_literal':
        return set()
    if node.type == 'identifier':
        return set(env.get(source.text(node), set()))
    if node.type in {'selector_expression', 'type_assertion_expression'}:
        return _deps(source, child(node,'operand'),env)
    return set().union(*(_deps(source,item,env) for item in node.named_children))


def _expression(source, node, env):
    return dict(code=source.text(node), span=span(source,node), syntax_node=node.type,
                formal_dependencies=sorted(_deps(source,node,env))) if node is not None else None


def _condition(source, expression, env, form, polarity, branch, case_patterns=()):
    operands = []
    for position in ['left','right','operand']:
        node = child(expression,position) if expression is not None else None
        if node is not None:
            operands.append(dict(position=position, **_expression(source,node,env)))
    if not operands and expression is not None:
        operands.append(dict(position='expression', **_expression(source,expression,env)))
    patterns = [_expression(source,node,env) for node in case_patterns]
    return dict(branch_span=span(source,branch), form=form, polarity=polarity,
        expression=_expression(source,expression,env), operands=operands, case_patterns=patterns,
        formal_dependencies=sorted(_deps(source,expression,env) | set().union(*(set(p['formal_dependencies']) for p in patterns))),
        status='syntactic_may_control', operator=source.text(child(expression,'operator')) if expression is not None else '')


def _merge(original, *alternatives):
    # A branch does not export new local names. Existing values are may joins.
    return {name:set(original[name]).union(*(row.get(name,set()) for row in alternatives)) for name in original}


def _declared(source,node):
    if node is None:
        return set()
    if node.type in {'short_var_declaration','var_spec'}:
        return _writes(source,node)
    if node.type in {'var_declaration','var_spec_list'}:
        return set().union(*(_declared(source,item) for item in node.named_children))
    return set()


def _restore(original,current,declared):
    return {name:set(original[name]) if name in declared else deps
            for name,deps in current.items() if name not in declared or name in original}


class _Body:
    def __init__(self, function):
        self.function, self.source = function, function['source']
        self.calls, self.unknowns = [], []

    def expression_calls(self, node, env, controls):
        if node is None:
            return
        if node.type == 'func_literal':
            self.unknowns.append(dict(reason='nested_function_body_unsupported',span=span(self.source,node)))
            return
        if node.type == 'call_expression':
            self.calls.append(dict(node=node, env={name:set(deps) for name,deps in env.items()}, controls=list(controls)))
        for item in node.named_children:
            self.expression_calls(item,env,controls)

    def visit(self, node, env, controls=(), scoped=True):
        if node is None:
            return env
        source = self.source
        kind = node.type
        if kind in {'block','statement_list'}:
            original,env,declared=dict(env),dict(env),set()
            for statement in _items(node):
                declared.update(_declared(source,statement))
                env = self.visit(statement,env,controls)
            return _restore(original,env,declared) if scoped else env
        if kind == 'if_statement':
            original=dict(env)
            initializer=child(node,'initializer')
            env = self.visit(initializer,dict(env),controls)
            condition = child(node,'condition')
            self.expression_calls(condition,env,controls)
            left = self.visit(child(node,'consequence'),dict(env),[*controls,_condition(source,condition,env,'if','true',node)])
            right = self.visit(child(node,'alternative'),dict(env),[*controls,_condition(source,condition,env,'if','false',node)])
            return _restore(original,_merge(env,left,right),_declared(source,initializer))
        if kind in {'type_switch_statement','expression_switch_statement'}:
            original=dict(env)
            initializer=child(node,'initializer')
            env = self.visit(initializer,dict(env),controls)
            value = child(node,'value')
            self.expression_calls(value,env,controls)
            branch_env = dict(env)
            for alias in _list(child(node,'alias')):
                if alias.type == 'identifier':
                    branch_env[source.text(alias)] = _deps(source,value,env)
            alternatives = []
            for case in node.named_children:
                if case.type not in {'type_case','expression_case','default_case'}:
                    continue
                patterns = [item for item in case.named_children if item.type != 'statement_list']
                control = _condition(source,value,env,kind,'default' if case.type=='default_case' else 'case_selected',case,patterns)
                local = dict(branch_env)
                for statement in case.named_children:
                    if statement.type == 'statement_list':
                        local = self.visit(statement,local,[*controls,control])
                alternatives.append(local)
            # Type-switch alias scope ends at the switch.
            aliases = {source.text(alias) for alias in _list(child(node,'alias'))}
            result = _merge(env,*alternatives)
            for name in aliases & env.keys():
                result[name] = env[name]
            return _restore(original,result,_declared(source,initializer))
        if kind in {'var_declaration','var_spec_list'}:
            for item in node.named_children:
                env=self.visit(item,env,controls)
            return env
        if kind in WRITES:
            values = _list(child(node,'right','value'))
            for value in values:
                self.expression_calls(value,env,controls)
            names = ([item for i,item in enumerate(node.named_children) if node.field_name_for_named_child(i)=='name']
                     if kind=='var_spec' else _list(child(node,'left','name')))
            before=dict(env)
            for i,name in enumerate(names):
                if name.type == 'identifier':
                    deps = _deps(source,values[i],before) if len(values)==len(names) else set().union(*(_deps(source,v,before) for v in values))
                    if source.text(child(node,'operator')) not in {'', '=', ':='}:
                        deps.update(before.get(source.text(name),set()))
                    env[source.text(name)] = deps
                else:
                    self.unknowns.append(dict(reason='nonlocal_write_dependency_unsupported',span=span(source,name)))
            return env
        if kind in {'for_statement','select_statement','go_statement','defer_statement'}:
            self.unknowns.append(dict(reason='control_or_scheduling_unsupported',span=span(source,node)))
            # Their bindings/scheduling are not modeled; do not attach an
            # outer formal to a shadowed loop identifier or promote a sink.
            return env
        self.expression_calls(node,env,controls)
        return env


def _arguments(source, arguments, target, env):
    params = target['parameters']
    variadic = bool(params and params[-1]['variadic'])
    fixed = len(params)-int(variadic)
    spreads = [i for i,arg in enumerate(arguments) if arg.type=='variadic_argument']
    if len(arguments)<fixed or not variadic and len(arguments)!=fixed:
        return [], 'argument_arity_mismatch'
    if spreads and (not variadic or spreads!=[len(arguments)-1] or len(arguments)!=fixed+1):
        return [], 'unsupported_spread_binding'
    result = []
    for i,formal in enumerate(params):
        actuals = arguments[i:] if formal['variadic'] else arguments[i:i+1]
        result.append(dict(formal=formal,actuals=[_expression(source,arg,env) for arg in actuals],variadic=formal['variadic']))
    return result, None


def analyze(sources):
    """Analyze finite same-directory Go package graphs; inputs are Source objects."""
    sources = sorted(sources,key=lambda source:source.path)
    functions, unknowns = [], []
    for source in sources:
        if source.language != 'go':
            unknowns.append(dict(reason='language_unsupported',path=source.path,language=source.language))
            continue
        if source.root.has_error:
            unknowns.append(dict(reason='source_parse_error',path=source.path))
            continue
        package = next((source.text(n.named_children[0]) for n in source.root.named_children if n.type=='package_clause' and n.named_children),'')
        source_sha = hashlib.sha256(source.data).hexdigest()
        for node in source.root.named_children:
            if node.type != 'function_declaration':
                continue
            params, reason = _parameters(source,node)
            if child(node,'body') is None:
                reason='function_body_unavailable'
            functions.append(dict(id=_id(source_sha,span(source,node)),name=source.text(child(node,'name')),
                span=span(source,node),package=dict(directory=posixpath.dirname(source.lookup_path),name=package),
                source_sha256=source_sha,code=source.text(node),parameters=params,status='source_function' if reason is None else 'unknown',reason=reason,
                node=node,source=source,can_reach_failure=False,condition_formal_dependencies=set(),check_call_ids=[]))
    by_name = defaultdict(list)
    for function in functions:
        by_name[function['package']['directory'],function['package']['name'],function['name']].append(function)
    calls, sinks, controls = [], [], {}
    for function in functions:
        source = function['source']
        if function['reason']:
            unknowns.append(dict(reason=function['reason'],function_id=function['id'],span=function['span']))
            continue
        body = child(function['node'],'body')
        writes = set().union(*(_writes(source,node) for node in _owned(body)))
        formals = {p['name']:p for p in function['parameters']}
        parsed = _Body(function)
        parsed.visit(body,{name:{name} for name in formals},scoped=False)
        unknowns.extend(dict(row,function_id=function['id']) for row in parsed.unknowns)
        for event in sorted(parsed.calls,key=lambda row:(row['node'].start_byte,row['node'].end_byte)):
            node, env = event['node'], event['env']
            callee, arguments = call_parts(node)
            row = dict(id=_id(function['id'],span(source,node)),span=span(source,node),code=source.text(node),callee=source.text(callee),
                caller_id=function['id'],target_id=None,status='unknown',reason='callee_not_same_package_static_function',actual_formal=[])
            if callee is not None and callee.type=='selector_expression':
                receiver, method = attr_parts(callee)
                name = source.text(receiver)
                if source.text(method) in SINK_METHODS:
                    formal = formals.get(name) if receiver is not None and receiver.type=='identifier' else None
                    if formal is None or not formal['testing_receiver'] or formal['variadic']:
                        row['reason']='testing_sink_receiver_type_unproved'
                    elif name in writes:
                        row['reason']='testing_sink_receiver_rebound'
                    else:
                        row.update(status='testing_sink',reason=None)
                        sinks.append(dict(call_id=row['id'],function_id=function['id'],span=row['span'],code=row['code'],
                            method=source.text(method),receiver_formal=formal,
                            diagnostic_arguments=[dict(code=source.text(arg),span=span(source,arg)) for arg in arguments]))
            elif callee is not None and callee.type=='identifier':
                candidates=by_name.get((function['package']['directory'],function['package']['name'],source.text(callee)),[])
                if source.text(callee) in formals or source.text(callee) in writes:
                    row['reason']='callee_shadowed_or_reassigned'
                elif len(candidates)>1:
                    row['reason']='same_package_function_ambiguous'
                elif len(candidates)==1:
                    target=candidates[0]
                    mapping, reason = _arguments(source,arguments,target,env)
                    reason = target['reason'] or reason
                    row.update(target_id=target['id'],actual_formal=mapping if reason is None else [],
                        status='same_package_static_call' if reason is None else 'unknown',reason=reason)
            calls.append(row)
            controls[row['id']]=event['controls']
            if row['reason'] and row['reason']!='callee_not_same_package_static_function':
                unknowns.append(dict(reason=row['reason'],call_id=row['id'],span=row['span']))
    lookup={function['id']:function for function in functions}
    for sink in sinks:
        lookup[sink['function_id']]['can_reach_failure']=True
    iterations=0
    while True:
        changed=False; iterations+=1
        for call in calls:
            if call['status']=='same_package_static_call' and lookup[call['target_id']]['can_reach_failure'] and not lookup[call['caller_id']]['can_reach_failure']:
                lookup[call['caller_id']]['can_reach_failure']=True;changed=True
        if not changed:
            break
    checks, conditions = [], []
    for call in calls:
        if call['status']!='testing_sink' and not (call['status']=='same_package_static_call' and lookup[call['target_id']]['can_reach_failure']):
            continue
        condition_ids=[]; deps=set()
        for i,control in enumerate(controls[call['id']]):
            identity=_id(call['id'],i,control)
            conditions.append(dict(control,id=identity,function_id=call['caller_id'],check_call_id=call['id']))
            condition_ids.append(identity);deps.update(control['formal_dependencies'])
        lookup[call['caller_id']]['condition_formal_dependencies'].update(deps)
        lookup[call['caller_id']]['check_call_ids'].append(call['id'])
        checks.append(dict(call_id=call['id'],function_id=call['caller_id'],target_id=call['target_id'],span=call['span'],code=call['code'],
            kind='direct_testing_sink' if call['status']=='testing_sink' else 'same_package_reachable_call',
            condition_ids=condition_ids,local_condition_formal_dependencies=sorted(deps),callee_condition_formal_dependencies=[]))
    dependency_iterations=0
    while True:
        changed=False;dependency_iterations+=1
        for call in calls:
            if call['status']!='same_package_static_call' or not lookup[call['target_id']]['can_reach_failure']:
                continue
            formal_deps=lookup[call['target_id']]['condition_formal_dependencies']
            mapped={name for binding in call['actual_formal'] if binding['formal']['name'] in formal_deps
                    for actual in binding['actuals'] for name in actual['formal_dependencies']}
            current=lookup[call['caller_id']]['condition_formal_dependencies']
            if not mapped <= current:
                current.update(mapped);changed=True
        if not changed:
            break
    call_lookup={call['id']:call for call in calls}
    for check in checks:
        call=call_lookup[check['call_id']]
        if call['target_id'] is not None:
            wanted=lookup[call['target_id']]['condition_formal_dependencies']
            check['callee_condition_formal_dependencies']=sorted({name for b in call['actual_formal'] if b['formal']['name'] in wanted
                for actual in b['actuals'] for name in actual['formal_dependencies']})
    for function in functions:
        function['condition_formal_dependencies']=sorted(function['condition_formal_dependencies'])
        if function['reason'] is None and any(row.get('function_id')==function['id'] for row in unknowns):
            function['status']='partial_unknown'
        del function['node'];del function['source']
    return dict(version=VERSION,status='source_analysis',functions=functions,sinks=sinks,calls=calls,conditions=conditions,checks=checks,unknowns=unknowns,
        counts=dict(sources=len(sources),functions=len(functions),testing_sinks=len(sinks),reachable_functions=sum(f['can_reach_failure'] for f in functions),
            checks=len(checks),conditions=len(conditions),reachability_iterations=iterations,dependency_iterations=dependency_iterations,
            unknown_reasons=dict(Counter(row['reason'] for row in unknowns))),
        limits=['Go top-level functions and same-directory same-package static calls only',
            'lexical may reachability, not execution or path feasibility',
            'syntactic may dependencies; unknown call effects, memory aliases and early exits are not modeled',
            'condition operand positions do not designate expected or actual',
            'diagnostic sink arguments are not checked values',
            'implementation behavior is not a correctness contract; no expected value or safe edit is inferred'])


def analyze_corpus(corpus, candidate=None):
    """Corpus convenience entry; optional candidate reparses program edits only."""
    if candidate is not None:
        sources, _, _, _, unknowns = _modified_sources(corpus,candidate)
    else:
        sources=[Source(path,row['code'],row.get('language',corpus['language']),row.get('origin','repository'),
                        row.get('step'),row.get('written_path')) for path,row in sorted(corpus['sources'].items())]
        unknowns=[]
    result=analyze(sources)
    result['unknowns'].extend(unknowns)
    return result
