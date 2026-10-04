"""Propose one None input edit while retaining the complete original test.

Issue identifiers retrieve fields. They do not establish a rejection contract.
Only a subsequent complete-test semantic review can admit a hypothesis. The
source role checks below are deliberately incomplete and abstain on ambiguity.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re

from relation_search import source_control_context as context
from relation_search import test_roles

VERSION = 'source-field-null-hypotheses.v1'
MAX_CANDIDATES = 16
POLICY = dict(
    version=VERSION, language='python', max_candidates=MAX_CANDIDATES,
    construction='Replace one non-None closed scalar field value with None in a complete original test containing assert or bound pytest.raises.',
    retrieval='A complete field identifier occurs in the public issue; this is a retrieval cue, never a null-rejection contract.',
    ordering='retrieval_rank, source path, value start byte',
    containers=['dictionary literal', 'static local dictionary subscript assignment',
                'unshadowed builtin dict keyword'],
    unchanged='All decorators, setup, operations, assertions, expected values and other bytes of the original test.',
    role_scope='Module-level tests; stable call argument bindings; unique direct local values; single-parameter literal pytest parametrization. Unknown aliases, mutation, helper or oracle roles abstain.',
    semantics='Every candidate is a source hypothesis. None may be valid. An unchanged original error assertion may be inappropriate or may fail to isolate this field.',
    admission='Require complete-test source-only semantic review. The driver specifies review placement, execution budgets and stop rules. Native failure text and audit labels do not establish the contract.',
    alert='Require whole-test contract support, repeated source-controlled failure, exact transport and a separate independent audit. Generation alone never establishes an alert.',
    forbidden_inputs=['case identities', 'census targets', 'audit labels', 'old candidates',
                      'runtime outcomes', 'hidden tests', 'reference implementations'],
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _scalar(node):
    if isinstance(node, ast.Constant):
        return type(node.value) in (str, int, float, bool)
    return (isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub))
            and isinstance(node.operand, ast.Constant)
            and type(node.operand.value) in (int, float))


def _inside(inner, outer):
    return (inner['path'] == outer['path']
            and outer['start_byte'] <= inner['start_byte'] < inner['end_byte'] <= outer['end_byte'])


class _Test:
    def __init__(self, path, code, tree, function, test):
        self.path, self.code, self.tree, self.fn, self.test = path, code, tree, function, test
        self.offsets = context._offsets(code)
        self.parents = {child: parent for parent in ast.walk(function) for child in ast.iter_child_nodes(parent)}
        self.imports = context._imports(tree)
        self.module_names, self.wildcard = context._module_bindings(tree)
        self.parameters, self.assigned, self.blocked = context._names(function)
        self.locals = {}
        self.functions = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions.setdefault(node.name, []).append(node)
        for node in context._walk(function):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.locals.setdefault(target.id, []).append(node)

    def span(self, node):
        return context._span(node, self.path, self.offsets, version='original')

    def receipt(self, node):
        position = self.span(node)
        return dict(position, source_sha256=hashlib.sha256(self.code.encode()).hexdigest(),
                    text=self.code.encode()[position['start_byte']:position['end_byte']].decode())

    def ancestors(self, node):
        while node in self.parents:
            node = self.parents[node]
            yield node

    def builtin(self, name):
        return not self.wildcard and not self.module_names[name] and name not in self.blocked

    def pytest_call(self, call, symbol):
        return (isinstance(call, ast.Call)
                and context._import_symbol(call.func, self.imports, self.blocked) == ('pytest', symbol))

    def oracle_context(self, node):
        for owner in self.ancestors(node):
            if isinstance(owner, (ast.Assert, ast.Raise, ast.Lambda)):
                return True
            if isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)) and owner is not self.fn:
                return True
            if isinstance(owner, ast.Call):
                imported = context._import_symbol(owner.func, self.imports, self.blocked)
                if imported and imported[0] == 'pytest' and not imported[1].startswith('mark.'):
                    return True
        return False

    def has_observation(self):
        return any(isinstance(n, ast.Assert) or
                   isinstance(n, (ast.With, ast.AsyncWith)) and any(
                       self.pytest_call(i.context_expr, 'raises') for i in n.items)
                   for n in context._walk(self.fn))

    def consumer(self, call):
        imported = context._import_symbol(call.func, self.imports, self.blocked)
        if imported and imported[0] != 'pytest' and imported[1]:
            return dict(kind='explicit_import_argument', binding=list(imported), call=self.receipt(call))
        if isinstance(call.func, ast.Name) and call.func.id not in self.blocked:
            declarations = self.functions.get(call.func.id, [])
            if len(declarations) == self.module_names[call.func.id] == 1:
                helper = declarations[0]
                # Assertion helpers require a more complete actual/formal
                # proof. Do not treat their arbitrary arguments as inputs.
                if not any(isinstance(n, (ast.Assert, ast.Raise)) or
                           isinstance(n, ast.Call) and self.pytest_call(n, 'raises')
                           for n in ast.walk(helper)):
                    return dict(kind='unique_source_function_argument', call=self.receipt(call),
                                declaration=self.receipt(helper))
        return None

    def local_flow(self, name, source_node, *, parameter=False, assignment=None, seen=()):
        if name in seen or len(seen) >= 8:
            raise ValueError('local_alias_depth_or_cycle')
        definitions = self.locals.get(name, [])
        if parameter:
            if name not in self.parameters or name in self.assigned:
                raise ValueError('parametrized_binding_reassigned')
        elif (name in self.parameters or len(definitions) != 1
              or definitions[0] not in self.fn.body):
            raise ValueError('local_definition_not_unique_direct')
        if not parameter and (sum(isinstance(n, ast.Name) and n.id == name
                                  and isinstance(n.ctx, (ast.Store, ast.Del))
                                  for n in context._walk(self.fn)) != 1
                or any(isinstance(n, (ast.Global, ast.Nonlocal)) and name in n.names
                       for n in context._walk(self.fn))):
            raise ValueError('local_binding_written_or_external')
        uses = [n for n in context._walk(self.fn) if isinstance(n, ast.Name)
                and n.id == name and isinstance(n.ctx, ast.Load)]
        if not uses:
            raise ValueError('no_input_consumption')
        proofs = []
        for use in uses:
            # The selected static subscript write is the sole allowed mutation.
            parent = self.parents.get(use)
            if (assignment is not None and isinstance(parent, ast.Subscript)
                    and self.parents.get(parent) is assignment):
                continue
            if not parameter and (use.lineno, use.col_offset) <= (source_node.lineno, source_node.col_offset):
                raise ValueError('local_read_before_input_definition')
            proofs.extend(self.flow(use, seen=(*seen, name)))
        if not proofs:
            raise ValueError('no_input_consumption')
        return proofs

    def flow(self, node, *, seen=()):
        if self.oracle_context(node):
            raise ValueError('oracle_or_nested_function_region')
        current = node
        while current in self.parents:
            parent = self.parents[current]
            if isinstance(parent, ast.Call):
                if isinstance(parent.func, ast.Name) and parent.func.id == 'dict' and self.builtin('dict'):
                    current = parent
                    continue
                proof = self.consumer(parent)
                if proof is None or current is parent.func:
                    raise ValueError('call_argument_binding_unresolved')
                return [dict(proof, argument=self.receipt(current))]
            if isinstance(parent, (ast.Assign, ast.AnnAssign)):
                targets = parent.targets if isinstance(parent, ast.Assign) else [parent.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name) or current is not parent.value:
                    raise ValueError('assignment_alias_or_mutation_unresolved')
                return self.local_flow(targets[0].id, parent, seen=seen)
            if isinstance(parent, (ast.Dict, ast.List, ast.Tuple, ast.keyword)):
                current = parent
                continue
            raise ValueError('input_value_flow_unresolved')
        raise ValueError('input_value_not_consumed')

    def input_flow(self, node, assignment=None):
        decorators = [d for d in self.fn.decorator_list if _inside(self.span(node), self.span(d))]
        if decorators:
            decorator = decorators[0]
            if (not self.pytest_call(decorator, 'mark.parametrize') or len(decorator.args) != 2
                    or decorator.keywords or not isinstance(decorator.args[0], ast.Constant)
                    or not isinstance(decorator.args[0].value, str)
                    or not re.fullmatch(r'[A-Za-z_]\w*', decorator.args[0].value)
                    or not isinstance(decorator.args[1], (ast.List, ast.Tuple))
                    or not _inside(self.span(node), self.span(decorator.args[1]))):
                raise ValueError('parameterization_binding_unsupported')
            return self.local_flow(decorator.args[0].value, decorator, parameter=True)
        if assignment is not None:
            target = assignment.targets[0] if isinstance(assignment, ast.Assign) else assignment.target
            if not isinstance(target.value, ast.Name) or assignment not in self.fn.body:
                raise ValueError('subscript_owner_or_phase_unresolved')
            name = target.value.id
            definitions = self.locals.get(name, [])
            if (len(definitions) != 1 or not isinstance(definitions[0].value, ast.Dict)
                    or definitions[0].lineno >= assignment.lineno):
                raise ValueError('subscript_owner_not_prior_local_dictionary')
            return self.local_flow(name, assignment, assignment=assignment)
        return self.flow(node)


def generate(corpus, frontend, issue, *, limit=16):
    """Return bounded source hypotheses; never execute or infer null illegality."""
    if type(limit) is not int or not 0 <= limit <= MAX_CANDIDATES:
        raise ValueError('limit must be an integer from 0 through 16')
    empty = dict(version=VERSION, candidates=[], catalog=[], total_candidates=0, selected=0, skipped=[])
    if corpus.get('language') != 'python':
        return dict(empty, status='language_unsupported')
    issue = issue.split('IMPORTANT:')[0]
    words = set(re.findall(r'(?<![A-Za-z0-9_])[A-Za-z_]\w*(?![A-Za-z0-9_])', issue))
    sources = {path: row for path, row in corpus['sources'].items() if row.get('origin') == 'repository'}
    role_corpus = dict(corpus, sources=sources, tests={k: t for k, t in corpus['tests'].items() if t['span']['path'] in sources})
    trees, role_cache, candidates, skipped = {}, {}, [], []
    for identifier, test in sorted(role_corpus['tests'].items()):
        path = test['span']['path']; row = sources[path]
        if row.get('language', corpus['language']) != 'python' or row.get('parse_error'):
            continue
        if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
            raise ValueError('frontend_source_mismatch:' + path)
        if path not in trees:
            try:
                trees[path] = ast.parse(row['code'])
            except (SyntaxError, ValueError):
                trees[path] = None
        tree = trees[path]
        if tree is None:
            continue
        functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == test['name'] and n.lineno == test['definition_span']['line']]
        if len(functions) != 1:
            continue
        scope = _Test(path, row['code'], tree, functions[0], test)
        if scope.wildcard or scope.module_names[scope.fn.name] != 1 or not scope.has_observation():
            continue
        original = test['span']; raw = row['code'].encode()
        full_span = context._span(scope.fn, path, scope.offsets, decorated=True)
        if any(original[k] != full_span[k] for k in ('start_byte', 'end_byte')):
            skipped.append(dict(base_test_id=identifier, reason='incomplete_original_test_span'))
            continue
        complete = dict(original, source_sha256=hashlib.sha256(raw).hexdigest(),
                        text=raw[original['start_byte']:original['end_byte']].decode())
        materials = []
        for node in ast.walk(scope.fn):
            if isinstance(node, ast.Dict):
                materials.extend((key.value, value, 'dictionary_literal', None)
                                 for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant))
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if len(targets) == 1 and isinstance(targets[0], ast.Subscript) and isinstance(targets[0].slice, ast.Constant):
                    materials.append((targets[0].slice.value, node.value, 'subscript_assignment', node))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'dict':
                if scope.builtin('dict'):
                    materials.extend((k.arg, k.value, 'builtin_dict_keyword', None) for k in node.keywords if k.arg)
        for field, node, container, assignment in materials:
            if (not isinstance(field, str) or not re.fullmatch(r'[A-Za-z_]\w*', field)
                    or field not in words or not _scalar(node)):
                continue
            position = scope.span(node)
            try:
                if not _inside(position, original):
                    raise ValueError('value_outside_complete_test_span')
                flow = scope.input_flow(node, assignment)
                if identifier not in role_cache:
                    role_cache[identifier] = test_roles.analyze(role_corpus, frontend,
                        dict(id='original_roles', base_test_id=identifier, edits=[], imports=[]))
                roles = role_cache[identifier]
                if any(u.get('code') in {'source_role_analysis_unavailable', 'modified_test_owner_not_recovered',
                                         'role_depth_budget', 'call_context_budget_or_recursion'} for u in roles['unknowns']):
                    raise ValueError('source_role_analysis_unresolved')
                value_uses = [position, *(binding['argument'] for binding in flow)]
                if any(r['role'] == 'expected' and any(_inside(use, r['span']) for use in value_uses)
                       for r in roles['roles']):
                    raise ValueError('source_expected_value_dependency')
            except ValueError as error:
                skipped.append(dict(base_test_id=identifier, field=field, span=position, reason=str(error)))
                continue
            edit = dict(span=position, before=scope.receipt(node)['text'], after='None', role='input')
            key = 'nullfield_' + digest([VERSION, identifier, edit])[:24]
            catalog = dict(field=field, container_kind=container, value=scope.receipt(node),
                           original_test=complete, input_argument_bindings=flow,
                           retrieval_rank=test.get('retrieval_rank', 10**9),
                           issue_sha256=hashlib.sha256(issue.encode()).hexdigest(),
                           semantic_status='source_hypothesis_requires_complete_contract_review',
                           null_illegality_established=False)
            candidates.append(dict(id=key, base_test_id=identifier, source_test_ids=[identifier], imports=[],
                edits=[edit], generator=VERSION, operator='replace_source_field_scalar_with_none',
                kind='source_input_hypothesis', oracle_status='unchanged_oracle_requires_semantic_review',
                source_evidence=catalog,
                order=[test.get('retrieval_rank', 10**9), path, position['start_byte']]))
    candidates.sort(key=lambda c: c['order'])
    chosen = candidates[:limit]
    return dict(version=VERSION, status='source_hypotheses', candidates=chosen,
                catalog=[dict(candidate_id=c['id'], **c['source_evidence']) for c in chosen],
                total_candidates=len(candidates), selected=len(chosen), skipped=skipped)
