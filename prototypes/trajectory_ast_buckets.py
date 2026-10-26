"""Source-provenance AST buckets for scheduling, never semantic equivalence.

This independent analysis prototype does not change the experiment pipeline.
It preserves literal values, operators, assertions, import bindings, origin
paths and the non-test file environment. Historical Go renames are reversed
only using the recorded relocation list and original-content hash. Unique
local bindings are alpha-numbered; shadowed or ambiguous names remain literal.
All candidates remain in the output permutation.
"""
from collections import defaultdict, deque
import hashlib
import json
import posixpath
import re

from anchor_retrieval.syntax import Source, child, walk


FUNCTIONS = {'function_definition', 'function_declaration', 'method_declaration',
             'function_expression', 'arrow_function', 'func_literal', 'lambda'}


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _origin(path, metadata):
    return metadata.get('original_target_path') or metadata.get('target_path') or path


def _relocations(metadata):
    if metadata.get('kind') != 'historical_validation' or not metadata.get('sha256'):
        return {}
    suffix = '_rh_' + metadata['sha256'][:12]
    return {name+suffix: name for name in metadata.get('relocated_globals', [])}


def _is_test(source, node, renames):
    if source.language != 'go' or node.type != 'function_declaration':
        return False
    name = child(node, 'name')
    spelling = renames.get(source.text(name), source.text(name)) if name is not None else ''
    parameters = child(node, 'parameters')
    parameters = [part for part in parameters.named_children if part.type != 'comment'] if parameters is not None else []
    if not re.match(r'^Test(?:[^a-z]|$)', spelling) or len(parameters) != 1:
        return False
    parameter = parameters[0]
    kind = source.text(child(parameter, 'type')).replace(' ', '')
    match = re.fullmatch(r'\*(\w+)\.T', kind)
    return (match is not None and source.imports.get(match[1], (None,))[0] == 'testing'
            and len(parameter.children_by_field_name('name')) <= 1 and child(node, 'result') is None)


def _identifiers(node):
    if node is None:
        return []
    if node.type == 'identifier':
        return [node]
    if node.type in {'expression_list', 'pattern_list', 'tuple_pattern', 'list_pattern', 'tuple', 'list'}:
        return [name for part in node.named_children for name in _identifiers(part)]
    return []


def _scope(node, language):
    while node is not None:
        if node.type in FUNCTIONS or (language != 'python' and node.type in {'block', 'statement_block'}):
            return node
        node = node.parent
    return None


def _unique_locals(source):
    """Bounded alpha-renaming: only one syntactic declaration per spelling.

    Same-spelling nested bindings, destructuring and unknown binding forms do
    not establish cross-snapshot sameness. Python fixture parameters stay named.
    """
    declarations, pinned = defaultdict(list), set()
    for node in walk(source.root):
        if source.language == 'python' and node.type in {'parameters', 'global_statement', 'nonlocal_statement'}:
            pinned.update(source.text(part) for part in walk(node) if part.type == 'identifier')
        names = []
        if node.type in {'short_var_declaration', 'assignment'}:
            names = _identifiers(child(node, 'left'))
        elif node.type in {'var_spec', 'variable_declarator'}:
            names = list(node.children_by_field_name('name'))
        elif source.language != 'python' and node.type in {'parameter_declaration', 'required_parameter'}:
            names = list(node.children_by_field_name('name'))
        for name in names:
            scope = _scope(node.parent, source.language)
            if name.type == 'identifier' and scope is not None and source.text(name) != '_':
                declarations[source.text(name)].append((name, node, scope))
    unique = [rows[0] for name, rows in declarations.items() if len(rows) == 1 and name not in pinned]
    unique.sort(key=lambda row: row[0].start_byte)
    return {source.text(name): (index, name, declaration, scope)
            for index, (name, declaration, scope) in enumerate(unique)}


def _shape(source, node, renames, imports, locals_=None, test_name=None, exclusions=()):
    if node.type == 'comment' or (node.start_byte, node.end_byte) in exclusions:
        return None
    if test_name is not None and node.id == test_name.id:
        return ['test_registration_name']
    text = source.text(node)
    if node.type in {'identifier', 'type_identifier'}:
        local = (locals_ or {}).get(text)
        if local is not None:
            index, name, declaration, scope = local
            parent = node.parent
            member = parent is not None and child(parent, 'attribute', 'property', 'field') == node
            # A Go keyed element may name a struct field instead of a variable.
            keyed = parent is not None and (parent.type == 'keyed_element' or
                    (parent.parent is not None and parent.parent.type == 'keyed_element'
                     and parent.parent.named_children[0] == parent))
            visible = (source.language == 'python' or node.id == name.id
                       or declaration.end_byte <= node.start_byte
                       or declaration.type in {'parameter_declaration', 'required_parameter'})
            if not member and not keyed and visible and scope.start_byte <= node.start_byte < scope.end_byte:
                return ['local_binding', index]
        text = renames.get(text, text)
        if text in imports:
            return ['import_binding', *imports[text]]
        return [node.type, text]
    if not node.children:
        return [node.type, text]
    values = []
    for index, part in enumerate(node.children):
        shape = _shape(source, part, renames, imports, locals_, test_name, exclusions)
        if shape is not None:
            values.append([node.field_name_for_child(index), shape])
    return [node.type, values]


class Buckets:
    def __init__(self, corpus, selection):
        self.corpus, self.selection = corpus, selection
        self.files, self.seeds, self.imports = {}, {}, {}

    def imported(self, owner, module, symbol):
        """Resolve to actual supplied source paths/content, never suffix text."""
        key = (owner, module, symbol)
        if key in self.imports:
            return self.imports[key]
        paths = []
        language = self.corpus['language']
        if language == 'go':
            for root, prefix in self.selection.get('module_resolution', {}).get('go_modules', {}).items():
                if module == prefix or module.startswith(prefix+'/'):
                    directory = posixpath.normpath(posixpath.join(root, module[len(prefix):].lstrip('/')))
                    paths.extend(path for path in self.corpus['sources']
                                 if (posixpath.dirname(path) or '.') == directory
                                 and path.endswith('.go') and not path.endswith('_test.go'))
        else:
            if language == 'python':
                dots = len(module)-len(module.lstrip('.'))
                directory = posixpath.dirname(owner)
                for _ in range(max(0, dots-1)):
                    directory = posixpath.dirname(directory)
                base = posixpath.join(directory, module[dots:].replace('.', '/')) if dots else module.replace('.', '/')
                guesses = [base+'.py', base+'/__init__.py', 'src/'+base+'.py', 'src/'+base+'/__init__.py']
            elif module.startswith('.'):
                base = posixpath.normpath(posixpath.join(posixpath.dirname(owner), module))
                stem, extension = posixpath.splitext(base)
                guesses = [base, base+'.ts', base+'.tsx', base+'/index.ts', base+'/index.tsx']
                if extension in {'.js', '.jsx', '.mjs', '.cjs'}:
                    guesses.extend([stem+'.ts', stem+'.tsx', stem+'.mts', stem+'.cts'])
            else:
                guesses = []
            paths = [path for path in guesses if path in self.corpus['sources']]
        declarations = [[path, hashlib.sha256(self.corpus['sources'][path]['code'].encode()).hexdigest()]
                        for path in sorted(set(paths))]
        identity = {'module': module, 'symbol': symbol,
                    'source_declarations': declarations,
                    'resolution': 'supplied_source' if declarations else 'external_or_unresolved'}
        if module.startswith('.'):
            identity['lookup_owner_directory'] = posixpath.dirname(owner)
        self.imports[key] = (json.dumps(identity, sort_keys=True), symbol)
        return self.imports[key]

    def file(self, path):
        if path in self.files:
            return self.files[path]
        metadata = self.selection.get('files', {}).get(path, {})
        original = _origin(path, metadata)
        entry = self.corpus['sources'][path]
        source = Source(path, entry['code'], self.corpus['language'])
        renames = _relocations(metadata)
        imports = {name: self.imported(original, module, symbol)
                   for name, (module, symbol) in source.imports.items()}
        excluded = {(node.start_byte, node.end_byte) for node in walk(source.root)
                    if _is_test(source, node, renames)}
        if source.language != 'go':
            excluded.update((test['span']['start_byte'], test['span']['end_byte'])
                            for test in self.corpus['tests'].values() if test['span']['path'] == path)
        identifier_counts = defaultdict(int)
        for node in walk(source.root):
            if node.type == 'identifier':
                identifier_counts[source.text(node)] += 1
        for node in walk(source.root):
            name = child(node, 'name') if node.type in FUNCTIONS else None
            if name is not None and identifier_counts[source.text(name)] > 1:
                # A test-shaped declaration can also be a callback/helper.
                # Keep it whenever any other syntactic occurrence could refer
                # to it, even when call resolution has no target for that use.
                excluded.discard((node.start_byte, node.end_byte))
        # Preserve explicitly referenced test-shaped helpers as dependencies.
        for test in self.corpus['tests'].values():
            if test['span']['path'] != path:
                continue
            for helper in test.get('support', {}).get('helpers', []):
                span = helper.get('span', {})
                if span.get('path') == path:
                    excluded.discard((span.get('start_byte'), span.get('end_byte')))
        environment = _shape(source, source.root, renames, imports, exclusions=excluded)
        self.files[path] = dict(source=source, renames=renames, imports=imports,
                                origin=original, environment=sha([original, environment]))
        return self.files[path]

    def unit(self, test_id, edits=(), additions=()):
        test = self.corpus['tests'][test_id]
        span = test['span']
        context = self.file(span['path'])
        original_node = context['source'].root.named_descendant_for_byte_range(span['start_byte'], span['end_byte']-1)
        scope = []
        ancestor = original_node.parent
        while ancestor is not None:
            if ancestor.type in {'class_definition', 'class_declaration', 'call_expression', 'call'}:
                # Preserve the actual enclosing class/suite and callback site,
                # not just the whole file that happens to contain both scopes.
                label = child(ancestor, 'name', 'function')
                scope.append([ancestor.type, context['source'].text(label),
                              ancestor.start_byte if ancestor.type in {'call_expression', 'call'} else None])
            ancestor = ancestor.parent
        code = context['source'].data[span['start_byte']:span['end_byte']]
        for edit in sorted(edits, key=lambda row: row['span']['start_byte'], reverse=True):
            where = edit['span']
            start, end = where['start_byte']-span['start_byte'], where['end_byte']-span['start_byte']
            if where['path'] != span['path'] or not 0 <= start <= end <= len(code):
                return {'opaque': sha([test_id, edits, additions]), 'status': 'unsupported_edit'}
            code = code[:start]+edit['after'].encode()+code[end:]
        language = self.corpus['language']
        text = code.decode()
        source = Source('unit', ('package bucket\n' if language == 'go' else '')+text, language)
        if source.root.has_error:
            return {'opaque': sha([test_id, edits, additions]), 'status': 'unsupported_parse'}
        function = next((node for node in source.root.named_children if node.type in FUNCTIONS), None)
        test_name = child(function, 'name') if function is not None else None
        imports = dict(context['imports'])
        for item in additions:
            owner = item.get('source_path', context['origin'])
            owner = _origin(owner, self.selection.get('files', {}).get(owner, {}))
            imports[item['name']] = self.imported(owner, item['module'], item.get('imported_name'))
        basic = _shape(source, source.root, context['renames'], imports, test_name=test_name)
        alpha = _shape(source, source.root, context['renames'], imports,
                       locals_=_unique_locals(source), test_name=test_name)
        return {'status': 'parsed', 'body': sha(basic), 'alpha': sha(alpha),
                'environment': sha([context['environment'], scope]), 'origin': context['origin'],
                'imports': sorted(set(imports.values()), key=repr)}

    def seed(self, test_id):
        if test_id not in self.seeds:
            self.seeds[test_id] = self.unit(test_id)
        return self.seeds[test_id]

    def candidate(self, candidate):
        seed = self.seed(candidate['base_test_id'])
        changed = self.unit(candidate['base_test_id'], candidate.get('edits', []), candidate.get('imports', []))
        def signature(record):
            return ([record['alpha'], record['environment'], record['imports']]
                    if record['status'] == 'parsed' else record)
        return sha([candidate.get('operator', candidate.get('kind')), signature(seed), signature(changed)])


def rank_all(candidates, keys):
    """Stable family→bucket→copy rounds; a permutation with no deletion."""
    groups = defaultdict(dict)
    for candidate in candidates:
        family = candidate.get('operator', candidate.get('kind', 'unknown'))
        groups[family].setdefault(keys[candidate['id']], deque()).append(candidate)
    queues = {family: deque(buckets.values()) for family, buckets in groups.items()}
    families = deque(sorted(queues))
    ranked = []
    while families:
        family = families.popleft()
        bucket = queues[family].popleft()
        ranked.append(bucket.popleft())
        if bucket:
            queues[family].append(bucket)
        if queues[family]:
            families.append(family)
    return ranked
