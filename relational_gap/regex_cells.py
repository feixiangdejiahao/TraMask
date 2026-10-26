"""Finite record coordinates discovered from source-owned parser captures.

Only import-proved Python regex operations supply grammars. Tests supply all
replacement values. Source code is never executed: an isolated, bounded worker
matches strings and verifies that recombination changes one capture coordinate.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
import json
import re
import subprocess
import sys

from anchor_retrieval.syntax import Source
from prototypes.finite_inputs import augment_corpus, _positions
from generic_composition.corpus import source_text
from generic_composition.engine import stable_id

from .embedded_relations import format_source_string
from .structured_ports import carrier_ports, structural_slot_key


@dataclass(frozen=True)
class RegexBudget:
    max_candidates: int = 128
    max_patterns: int = 32
    max_pattern_bytes: int = 2048
    max_input_bytes: int = 2048
    max_inputs_per_slot: int = 48
    max_groups: int = 24
    max_coordinates: int = 12
    max_attempts: int = 1024
    max_match_batches: int = 96
    max_depth: int = 4
    worker_timeout_ms: int = 1200
    allow_proximity: bool = True

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key != 'allow_proximity' and (type(value) is not int or value < 1):
                raise ValueError('Regex budgets must be positive integers')


def _position(item):
    span = item.get('span', item)
    return span['path'], span['start_byte'], span['end_byte']


class _SourceFacts:
    def __init__(self, source, functions):
        self.source = source
        self.tree = ast.parse(source.code)
        self.position = _positions(source.code)
        self.parents = {nested: parent for parent in ast.walk(self.tree) for nested in ast.iter_child_nodes(parent)}
        self.functions = {f['span']['start_byte']: f for f in functions if f['span']['path'] == source.path}
        self.nodes = {self.position(n): n for n in ast.walk(self.tree) if self.position(n) is not None}
        self.registry = {}
        self.definitions, self.imports, self.writes = defaultdict(lambda: defaultdict(list)), defaultdict(dict), defaultdict(Counter)
        self.scope_directives, self.import_counts = defaultdict(set), defaultdict(Counter)
        for node in ast.walk(self.tree):
            scope = self.scope(node)
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname or alias.name.split('.')[0]
                    self.imports[scope][name] = (alias.name, None)
                    self.import_counts[scope][name] += 1
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    name = alias.asname or alias.name
                    self.imports[scope][name] = ('.' * node.level + (node.module or ''), alias.name)
                    self.import_counts[scope][name] += 1
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                self.scope_directives[scope].update(node.names)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        self.definitions[scope][target.id].append((node, node.value))
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                self.writes[scope][node.id] += 1
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                self.writes[scope][node.name] += 1
            elif isinstance(node, ast.arg):
                self.writes[scope][node.arg] += 1

    def scope(self, node):
        parent = self.parents.get(node)
        while parent is not None and not isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            parent = self.parents.get(parent)
        return parent or self.tree

    def function(self, node):
        parent = node
        while parent is not None:
            if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                position = self.position(parent)
                return self.functions.get(position[0]) if position else None
            parent = self.parents.get(parent)
        return None

    def span(self, node):
        start, end = self.position(node)
        return {'path': self.source.path, 'start_byte': start, 'end_byte': end}

    def import_identity(self, name, node):
        for scope in self.lexical_scopes(node):
            if self.writes[scope][name] or name in self.scope_directives[scope] or '*' in self.imports[scope]:
                return None
            if name in self.imports[scope]:
                return self.imports[scope][name] if self.import_counts[scope][name] == 1 else None
        return None

    def lexical_scopes(self, node):
        scope = self.scope(node)
        yield scope
        while scope is not self.tree:
            scope = self.scope(scope)
            # Python methods/nested classes do not close over class namespaces.
            if not isinstance(scope, ast.ClassDef):
                yield scope

    def re_api(self, node):
        if isinstance(node, ast.Name):
            identity = self.import_identity(node.id, node)
            return identity[1] if identity and identity[0] == 're' else None
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.attr if self.import_identity(node.value.id, node) == ('re', None) else None
        return None

    def definition(self, name, use):
        choices = []
        for scope in self.lexical_scopes(use):
            if name in self.scope_directives[scope] or name in self.imports[scope] or '*' in self.imports[scope]:
                return None
            if name in self.definitions[scope] or self.writes[scope][name]:
                choices = self.definitions[scope].get(name, [])
                break
        if len(choices) != 1 or choices[0][1] is None or self.writes[scope][name] != 1:
            return None
        declaration, value = choices[0]
        if self.scope(declaration) is not self.tree and self.position(declaration)[1] > self.position(use)[0]:
            return None
        parent = self.parents.get(declaration)
        while parent is not None and parent is not self.scope(declaration):
            if isinstance(parent, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)):
                return None
            parent = self.parents.get(parent)
        return value

    def static(self, node, seen=()):
        if isinstance(node, ast.Constant) and type(node.value) in {str, int}:
            return node.value
        if isinstance(node, ast.Name) and node.id not in seen:
            definition = self.definition(node.id, node)
            if definition is not None:
                return self.static(definition, (*seen, node.id))
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitOr, ast.Add)):
            left, right = self.static(node.left, seen), self.static(node.right, seen)
            if type(left) is int and type(right) is int and isinstance(node.op, ast.BitOr):
                return left | right
            if type(left) is str and type(right) is str and isinstance(node.op, ast.Add):
                return left + right
        flag = self.re_api(node) if node is not None else None
        if flag in {'I', 'IGNORECASE', 'M', 'MULTILINE', 'S', 'DOTALL', 'X', 'VERBOSE', 'A', 'ASCII', 'U', 'UNICODE', 'NOFLAG'}:
            return int(getattr(re, flag))
        return None

    def compiled(self, node, seen=()):
        if isinstance(node, ast.Name) and node.id not in seen:
            definition = self.definition(node.id, node)
            if definition is not None:
                return self.compiled(definition, (*seen, node.id))
            return self.imported_compiled(self.import_identity(node.id, node), seen)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            imported = self.import_identity(node.value.id, node)
            if imported and imported[1] is None:
                resolved = self.imported_compiled((imported[0], node.attr), seen)
                if resolved is not None:
                    return resolved
            scope = self.scope(node)
            owner = self.parents.get(scope)
            if isinstance(owner, ast.ClassDef) and isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                receiver = scope.args.args[0].arg if scope.args.args else None
                if node.value.id in {receiver, owner.name}:
                    choices = self.definitions[owner].get(node.attr, [])
                    writes = [n for n in ast.walk(owner) if isinstance(n, ast.Attribute)
                              and n.attr == node.attr and isinstance(n.ctx, (ast.Store, ast.Del))]
                    if len(choices) == 1 and self.writes[owner][node.attr] == 1 and not writes:
                        return self.compiled(choices[0][1], (*seen, node.attr))
                    # One source assignment to an instance field can carry a
                    # compiled regex from the constructor to its parser method.
                    if not choices and len(writes) == 1:
                        target = writes[0]
                        declaration = self.parents.get(target)
                        method = self.scope(target)
                        bound_receiver = method.args.args[0].arg if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.args.args else None
                        if (isinstance(declaration, (ast.Assign, ast.AnnAssign)) and isinstance(target.value, ast.Name)
                                and target.value.id == bound_receiver and bound_receiver is not None):
                            return self.compiled(declaration.value, (*seen, node.attr))
        if isinstance(node, ast.Call) and self.re_api(node.func) == 'compile':
            pattern = _argument(node, 0, 'pattern')
            flags = _argument(node, 1, 'flags')
            value, flag_value = self.static(pattern), self.static(flags) if flags is not None else 0
            if type(value) is str and type(flag_value) is int:
                return value, flag_value, self.span(pattern), self.span(node)
        return None

    def imported_compiled(self, identity, seen):
        if identity is None or identity[1] is None or len(seen) > 8:
            return None
        from .source_dependencies import _python_paths
        module, name = identity
        level = len(module) - len(module.lstrip('.'))
        paths, _ = _python_paths(self.registry, self.source.path, module.lstrip('.'), level, [])
        choices = []
        for path in paths:
            fact = self.registry[path]
            key = path, name
            if key in seen:
                continue
            definitions = fact.definitions[fact.tree].get(name, [])
            value = None
            if len(definitions) == 1 and fact.writes[fact.tree][name] == 1:
                value = fact.compiled(definitions[0][1], (*seen, key))
            elif not fact.writes[fact.tree][name]:
                value = fact.imported_compiled(fact.imports[fact.tree].get(name), (*seen, key))
            if value is not None:
                choices.append(value)
        return choices[0] if len(choices) == 1 else None

    def formal(self, node, function, seen=()):
        if not isinstance(node, ast.Name):
            return None
        choices = [p for p in function['parameters'] if p.get('name') == node.id]
        scope = self.scope(node)
        if choices:
            # The parameter's ast.arg is its one binding. Any later write is
            # outside this exact flow proof, including augmented assignment.
            return choices[0]['index'] if self.writes[scope][node.id] == 1 else None
        if node.id in seen:
            return None
        return self.formal(self.definition(node.id, node), function, (*seen, node.id))


def _argument(call, index, name):
    return call.args[index] if len(call.args) > index else next((k.value for k in call.keywords if k.arg == name), None)


def _patterns(facts, budget, skipped):
    found = []
    for fact in facts.values():
        for node in ast.walk(fact.tree):
            if not isinstance(node, ast.Call):
                continue
            function = fact.function(node)
            if function is None or function.get('test'):
                continue
            method = fact.re_api(node.func)
            compiled = None
            if method in {'match', 'fullmatch', 'search'}:
                pattern = _argument(node, 0, 'pattern')
                flags = _argument(node, 2, 'flags')
                text, flag_value = fact.static(pattern), fact.static(flags) if flags is not None else 0
                if type(text) is str and type(flag_value) is int:
                    compiled = text, flag_value, fact.span(pattern), fact.span(node)
                actual = _argument(node, 1, 'string')
            elif isinstance(node.func, ast.Attribute) and node.func.attr in {'match', 'fullmatch', 'search'}:
                method = node.func.attr
                compiled = fact.compiled(node.func.value)
                actual = _argument(node, 0, 'string')
                if len(node.args) > 1 or any(k.arg != 'string' for k in node.keywords):
                    compiled = None  # pos/endpos require a separate coordinate frame.
            else:
                continue
            if compiled is None or actual is None:
                continue
            text, flags, pattern_span, declaration_span = compiled
            if len(text.encode()) > budget.max_pattern_bytes:
                skipped['pattern_size_budget'] += 1
                continue
            found.append({'id': stable_id('source-regex', fact.span(node), text, flags), 'pattern': text, 'flags': flags,
                          'method': method, 'pattern_span': pattern_span, 'declaration_span': declaration_span,
                          'use_span': fact.span(node), 'function_id': function['id'], 'owner': function.get('owner', ''),
                          'parameter_index': fact.formal(actual, function), 'input_span': fact.span(actual),
                          'api_identity': 'python.re.' + method})
    return sorted(found, key=lambda p: (p['parameter_index'] is None, _position(p['use_span']), p['id']))[:budget.max_patterns]


def _flow(pattern, frontend, facts, budget):
    incoming = defaultdict(list)
    for call in frontend.get('calls', []) + frontend.get('production_calls', []):
        if call.get('test_id') is not None and call.get('role') != 'operation':
            continue
        for binding in call.get('argument_bindings', []):
            if binding.get('binding_status') != 'direct_actual_formal':
                continue
            if not any(t['function_id'] == binding['function_id'] and t.get('resolved') for t in call.get('targets', [])):
                continue
            incoming[binding['function_id'], binding['parameter_index']].append((call, binding))
    if pattern['parameter_index'] is None:
        return {}
    functions = {f['id']: f for f in frontend.get('functions', [])}
    queue = deque([(pattern['function_id'], pattern['parameter_index'], [], 0)])
    output, seen = {}, set()
    while queue and len(seen) < 256:
        fid, parameter, trail, depth = queue.popleft()
        if (fid, parameter) in seen or depth >= budget.max_depth:
            continue
        seen.add((fid, parameter))
        for call, binding in incoming[fid, parameter]:
            path = [call['span'], *trail]
            if call.get('test_id') is not None:
                output[_position(call), binding['slot']] = path
                continue
            caller = functions.get(call.get('function_id'))
            fact = facts.get(call['span']['path'])
            actual = next((a for a in call['arguments'] if a['slot'] == binding['slot']), None)
            if caller and fact and actual:
                node = fact.nodes.get((actual['span']['start_byte'], actual['span']['end_byte']))
                parent = fact.formal(node, caller)
                if parent is not None:
                    queue.append((caller['id'], parent, path, depth + 1))
    return output


def _proximity(pattern, port, context, budget):
    position = _position(port['call_span'])
    call = context['calls'].get(position)
    if call is None:
        return False
    if position not in context['reachable']:
        queue = deque((t['function_id'], 0) for t in call.get('targets', []))
        seen, owners = set(), set()
        while queue and len(seen) < 256:
            fid, depth = queue.popleft()
            if fid in seen or depth >= budget.max_depth:
                continue
            seen.add(fid)
            function = context['functions'].get(fid)
            if function:
                owners.add((function['span']['path'], function.get('owner', '')))
            queue.extend((target, depth + 1) for target in context['forwarding'][fid])
        context['reachable'][position] = seen, owners
    reached, owners = context['reachable'][position]
    return (pattern['function_id'] in reached or (pattern['use_span']['path'], pattern['owner']) in owners
            or port['call_span']['path'] == pattern['use_span']['path'])


_WORKER = r'''
import json, re, sys
from re import _parser, _constants
p=json.load(sys.stdin)
try:
 compiled=re.compile(p['pattern'], p['flags'])
 if compiled.groups > p['max_groups']: raise ValueError('capture_group_budget')
 ancestors={}
 def visit(items, parents=()):
  for op,arg in items:
   if op is _constants.SUBPATTERN:
    group,_,_,sub=arg
    if group: ancestors[group]=list(parents)
    visit(sub, parents+(group,) if group else parents)
   elif op is _constants.BRANCH:
    for branch in arg[1]: visit(branch,parents)
   elif op in {_constants.MAX_REPEAT,_constants.MIN_REPEAT,_constants.POSSESSIVE_REPEAT}: visit(arg[2],parents)
   elif op in {_constants.ASSERT,_constants.ASSERT_NOT}: visit(arg[1],parents)
   elif op is _constants.ATOMIC_GROUP: visit(arg,parents)
 visit(_parser.parse(p['pattern'],p['flags']))
 out=[]
 for text in p['inputs']:
  match=getattr(compiled,p['method'])(text)
  out.append(None if match is None else {'span':list(match.span()),'groups':[match.group(i) for i in range(1,compiled.groups+1)],'spans':[list(match.span(i)) for i in range(1,compiled.groups+1)]})
 print(json.dumps({'matches':out,'ancestors':ancestors,'names':dict(compiled.groupindex)},ensure_ascii=True))
except (ValueError,re.error,OverflowError,RuntimeError,RecursionError) as exc:
 print(json.dumps({'error':str(exc)}))
'''


def _match(pattern, inputs, budget, skipped):
    if skipped['match_batches_used'] >= budget.max_match_batches:
        skipped['match_batch_budget'] += 1
        return None
    skipped['match_batches_used'] += 1
    try:
        result = subprocess.run([sys.executable, '-I', '-c', _WORKER], input=json.dumps(dict(pattern=pattern['pattern'], flags=pattern['flags'],
                                 method=pattern['method'], inputs=inputs, max_groups=budget.max_groups)),
                                capture_output=True, text=True, timeout=budget.worker_timeout_ms / 1000, check=False)
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        skipped['regex_worker_timeout'] += 1
        return None
    except (OSError, ValueError):
        skipped['regex_worker_failed'] += 1
        return None
    if result.returncode or data.get('error'):
        skipped['unsupported_regex_or_capture_budget'] += 1
        return None
    return data


def _coordinates(match, ancestors):
    active = {i + 1 for i, (a, b) in enumerate(match['spans']) if a >= 0 and b > a}
    leaves = [i for i in active if not any(i in ancestors.get(str(j), []) for j in active if j != i)]
    return [i for i in sorted(leaves) if not any(max(match['spans'][i - 1][0], match['spans'][j - 1][0])
                                               < min(match['spans'][i - 1][1], match['spans'][j - 1][1]) for j in leaves if j != i)]


def _same_other_coordinates(before, after, group, replacement, ancestors):
    if after is None or len(before['groups']) != len(after['groups']):
        return False
    start, end = before['spans'][group - 1]
    delta = len(replacement) - (end - start)
    if after['span'] != [before['span'][0], before['span'][1] + delta] or after['spans'][group - 1] != [start, start + len(replacement)]:
        return False
    if after['groups'][group - 1] != replacement:
        return False
    parents = ancestors.get(str(group), [])
    for i, old in enumerate(before['groups'], 1):
        if i == group:
            continue
        expected = old
        if i in parents:
            a, _ = before['spans'][i - 1]
            expected = old[:start - a] + replacement + old[end - a:]
        if after['groups'][i - 1] != expected:
            return False
        a, b = before['spans'][i - 1]
        if a < 0:
            expected_span = [a, b]
        elif i in parents:
            expected_span = [a, b + delta]
        elif b <= start:
            expected_span = [a, b]
        elif a >= end:
            expected_span = [a + delta, b + delta]
        else:
            return False  # An unrelated coordinate overlaps the edited leaf.
        if after['spans'][i - 1] != expected_span:
            return False
    return True


def _finite(corpus):
    rows = []
    for test in corpus['tests'].values():
        for row in test.get('parameter_rows', []):
            rows.append(dict(row, id=stable_id('regex-source-row', test['id'], row['table'], row['row']), kind='parameter_row',
                             test_id=test['id'], span=row['row_span'], parameter_bindings=row['bindings']))
    return augment_corpus(dict(corpus, donors=[*corpus['donors'], *rows]))


def _row_edits(corpus, donor, facts):
    row = donor.get('parameter_row')
    if not row:
        return [], None
    if not donor.get('finite_input'):
        return None, None
    test = corpus['tests'][donor['test_id']]
    fact = facts[donor['span']['path']]
    function = fact.nodes.get((test['definition_span']['start_byte'], test['definition_span']['end_byte']))
    if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)) or len(function.decorator_list) != 1:
        return None, None
    decorator = function.decorator_list[0]
    if not isinstance(decorator, ast.Call) or len(decorator.args) < 2 or not isinstance(decorator.args[1], (ast.List, ast.Tuple)):
        return None, None
    table = decorator.args[1]
    if not 0 <= row['row'] < len(table.elts):
        return None, None
    chosen = table.elts[row['row']]
    edits = [{'span': fact.span(table), 'before': source_text(corpus, fact.span(table)),
              'after': '[' + source_text(corpus, fact.span(chosen)) + ']'}]
    for option in decorator.keywords:
        if option.arg == 'ids':
            if not isinstance(option.value, (ast.List, ast.Tuple)) or len(option.value.elts) != len(table.elts):
                return None, None
            edits.append({'span': fact.span(option.value), 'before': source_text(corpus, fact.span(option.value)),
                          'after': '[' + source_text(corpus, fact.span(option.value.elts[row['row']])) + ']'})
    return edits, {'table': row['table'], 'row': row['row'], 'bindings': row['bindings'],
                   'mode': 'complete_original_parameter_row_restricted_before_closed_input_edit'}


def generate_regex_cells(corpus: dict, frontend: dict, *, budget: RegexBudget | None = None) -> dict:
    budget = budget or RegexBudget()
    skipped, unknowns = Counter(), []
    sources, facts = {}, {}
    for path, metadata in corpus['sources'].items():
        if metadata.get('language', corpus['language']) != 'python' or metadata.get('parse_error') or not metadata.get('complete_file', True):
            continue
        source = Source(path, metadata['code'], 'python')
        try:
            facts[path] = _SourceFacts(source, frontend.get('functions', []))
        except (SyntaxError, ValueError):
            continue
        sources[path] = source
    for fact in facts.values():
        fact.registry = facts
    patterns = _patterns(facts, budget, skipped)
    enriched = _finite(corpus) if sources else corpus
    tests = corpus['tests']
    capsules = defaultdict(list)
    for capsule in corpus.get('capsules', []):
        capsules[capsule['test_id']].append(capsule)
    groups = defaultdict(list)
    for donor in enriched['donors']:
        if (donor.get('kind') == 'parameter_row' or donor['test_id'] not in tests or donor['span']['path'] not in sources
                or not capsules[donor['test_id']] or donor.get('oracle_dependency') or donor.get('diagnostic')
                or not donor.get('literal_known') or type(donor.get('literal_value')) is not str):
            continue
        if len(donor['literal_value'].encode()) > budget.max_input_bytes:
            skipped['input_size_budget'] += 1
            continue
        if source_text(corpus, donor['span']) != donor['text']:
            continue
        for port in carrier_ports(sources[donor['span']['path']], donor, frontend):
            if port.get('structural_path'):
                continue  # Whole-formal flow cannot identify an object field.
            groups[structural_slot_key(port)].append((donor, port))
    pool, attempts, matched_patterns = {}, 0, 0
    call_map = {_position(c): c for c in frontend.get('calls', [])}
    context = {'calls': call_map, 'functions': {f['id']: f for f in frontend.get('functions', [])},
               'forwarding': defaultdict(list), 'reachable': {}}
    for call in frontend.get('production_calls', []):
        context['forwarding'][call['function_id']].extend(t['function_id'] for t in call.get('targets', []))
    for pattern in patterns:
        exact = _flow(pattern, frontend, facts, budget)
        for key, available in sorted(groups.items(), key=lambda item: repr(item[0])):
            members = []
            for donor, port in available:
                proof = exact.get((_position(port['call_span']), port['argument_slot']))
                other_slot_proved = any(position == _position(port['call_span']) for position, _ in exact)
                if proof is not None or not other_slot_proved and budget.allow_proximity and _proximity(pattern, port, context, budget):
                    members.append((donor, port, proof))
            members.sort(key=lambda row: (row[2] is None, tests[row[0]['test_id']].get('retrieval_rank') or 10**9,
                                          _position(row[0]), row[0]['id']))
            members = members[:budget.max_inputs_per_slot]
            if len({d['literal_value'] for d, _, _ in members}) < 2:
                continue
            matches = _match(pattern, [d['literal_value'] for d, _, _ in members], budget, skipped)
            if matches is None:
                continue
            matched = [(entry, match) for entry, match in zip(members, matches['matches']) if match is not None]
            if len({entry[0]['literal_value'] for entry, _ in matched}) < 2:
                continue
            matched_patterns += 1
            proposals = []
            for (target, port, proof), before in matched:
                row_edits, instantiation = _row_edits(corpus, target, facts)
                if row_edits is None:
                    skipped['complete_row_instantiation_unavailable'] += 1
                    continue
                call = call_map.get(_position(port['call_span']), {})
                observation_ids = call.get('observation_ids', [])
                for group in _coordinates(before, matches['ancestors'])[:budget.max_coordinates]:
                    start, end = before['spans'][group - 1]
                    for (origin, _, _), other in matched:
                        replacement = other['groups'][group - 1]
                        if replacement is None or replacement == before['groups'][group - 1]:
                            continue
                        value = target['literal_value'][:start] + replacement + target['literal_value'][end:]
                        if len(value.encode()) > budget.max_input_bytes:
                            continue
                        # Seen values only establish novelty at the same q and
                        # unchanged parameter row, not across different tests.
                        already = any(d['test_id'] == target['test_id'] and d.get('parameter_row') == target.get('parameter_row')
                                      and d['literal_value'] == value and observation_ids
                                      and call_map.get(_position(p['call_span']), {}).get('observation_ids') == observation_ids
                                      for (d, p, _), _ in matched)
                        if already and proof is not None:
                            skipped['already_observed_same_q_input'] += 1
                            continue
                        after = (repr(value) if target.get('finite_input') else format_source_string(value, 'python', target['text']))
                        if after is None:
                            continue
                        edit = {'span': target['span'], 'before': target['text'], 'after': after}
                        identifier = stable_id('regex-coordinate', target['test_id'], [edit, *row_edits])
                        if identifier in pool or any(p[0] == identifier for p in proposals):
                            continue
                        proposals.append((identifier, value, target, origin, port, proof, before, group, replacement,
                                          [edit, *row_edits], instantiation, observation_ids))
                        attempts += 1
                        if attempts >= budget.max_attempts:
                            break
                    if attempts >= budget.max_attempts:
                        break
                if attempts >= budget.max_attempts:
                    break
            if proposals:
                checked = _match(pattern, [p[1] for p in proposals], budget, skipped)
                if checked is not None:
                    for proposal, match in zip(proposals, checked['matches']):
                        identifier, value, target, origin, port, proof, before, group, replacement, edits, instantiation, observation_ids = proposal
                        if not _same_other_coordinates(before, match, group, replacement, matches['ancestors']):
                            skipped['rematch_changed_other_coordinate_or_invalid'] += 1
                            continue
                        start, end = before['spans'][group - 1]
                        name = next((name for name, index in matches['names'].items() if index == group), None)
                        evidence = [pattern['pattern_span'], pattern['declaration_span'], pattern['use_span'], target['span'], origin['span'], *(proof or [])]
                        pool[identifier] = {'id': identifier, 'kind': 'source_regex_capture_coordinate', 'base_test_id': target['test_id'],
                            'focus_test_id': target['test_id'], 'source_test_ids': sorted({target['test_id'], origin['test_id']}),
                            'language': 'python', 'edits': edits, 'imports': [],
                            'relation': {'domain': 'source_regex_capture', 'pattern_id': pattern['id'], 'group': group, 'group_name': name,
                                         'capture_coordinate': {'unicode_span': [start, end], 'utf8_span': [len(target['literal_value'][:start].encode()), len(target['literal_value'][:end].encode())]},
                                         'before': before['groups'][group - 1], 'after': replacement,
                                         'input_slot': list(key), 'source_observation_ids': observation_ids,
                                         'binding_status': 'source_actual_formal_flow' if proof is not None else 'source_owner_proximity_unresolved',
                                         'binding_path': proof or [], 'rematch': 'only_selected_leaf_and_ancestor_captures_changed',
                                         'parameter_instantiation': instantiation,
                                         'status': 'source_grammar_hypothesis_runtime_unconfirmed'},
                            'oracle': {'mode': 'retain_all', 'source_test_id': target['test_id'],
                                       'assertion_ids': [c['id'] for c in capsules[target['test_id']]], 'applicability': 'requires_independent_admission'},
                            'provenance': {'source_spans': evidence, 'target_span': target['span'], 'source_donor_ids': [target['id'], origin['id']],
                                           'pattern': pattern, 'source_input': target['literal_value'], 'source_coordinate_input': origin['literal_value']},
                            'selection': {'proof_order': 0 if proof is not None else 1,
                                          'focus_order': tests[target['test_id']].get('retrieval_rank') or 10**9,
                                          'edit_size': sum(max(len(e['before'].encode()), len(e['after'].encode())) for e in edits)}}
            if attempts >= budget.max_attempts:
                break
        if attempts >= budget.max_attempts:
            break
    queues = defaultdict(deque)
    for candidate in sorted(pool.values(), key=lambda c: (c['selection']['proof_order'], c['selection']['focus_order'], c['base_test_id'], c['id'])):
        queues[candidate['base_test_id']].append(candidate)
    candidates = []
    while queues and len(candidates) < budget.max_candidates:
        for test_id in list(queues):
            candidates.append(queues[test_id].popleft())
            if not queues[test_id]:
                del queues[test_id]
            if len(candidates) >= budget.max_candidates:
                break
    return {'candidates': candidates, 'patterns': patterns, 'unknowns': unknowns, 'budget': asdict(budget),
            'counts': {'patterns': len(patterns), 'matched_pattern_slots': matched_patterns, 'pool': len(pool), 'candidates': len(candidates),
                       'attempts': attempts, 'attempt_budget_exhausted': attempts >= budget.max_attempts, 'skipped': dict(skipped)},
            'finite_inputs': enriched.get('finite_inputs', {})}
