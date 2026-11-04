"""Parameterised comparison templates; members remain concrete occurrences.

Equal templates share alignment work. They do not prove behavioral equivalence
and do not license removing differences in their retained parameter domains.
"""
from .evidence import STRINGS
from .relational_alignment import digest

NUMBERS = {'integer', 'int_literal', 'float', 'float_literal', 'number',
           'integer_literal', 'number_literal', 'imaginary_literal',
           'decimal_integer_literal', 'hex_integer_literal',
           'binary_integer_literal', 'octal_integer_literal'}


def term_template(term, *, strings=False):
    """Keep AST roles, fixed fields, operators, and within-term equalities."""
    names, parameters, values, out = {}, {}, [], []
    pending = [(term, False)]
    while pending:
        item, field_key = pending.pop()
        if isinstance(item, str):
            out.append(item)
            continue
        value = item.value
        if item.kind == 'reference':
            value = names.setdefault(value, len(names))
        elif item.kind in NUMBERS or strings and item.kind in STRINGS and not field_key:
            parameter = item.kind, value
            value = ('parameter', parameters.setdefault(parameter, len(parameters)))
            values.append(parameter)
        out.append((item.kind, value, len(item.children)))
        for role, child in reversed(item.children):
            pending.extend([(child, field_key or role.startswith('key:')), (role, False)])
    return digest(out), values


class TemplateProjection:
    def __init__(self, index):
        self.index = index
        self.syntax = {'numbers': {}, 'literals': {}}
        for (source, span), sha in index.syntax.items():
            term = index.terms[source].term(span)
            self.syntax['numbers'][sha] = term_template(term)
            self.syntax['literals'][sha] = term_template(term, strings=True)
        self.cache = {}

    def component(self, mode, kind, sha):
        key = mode, kind, sha
        if key in self.cache:
            return self.cache[key]
        parameters = []
        syntax = self.syntax[mode]

        def project(value):
            if isinstance(value, str) and value in syntax:
                shape, values = syntax[value]
                parameters.extend(values)
                return shape
            if isinstance(value, (list, tuple)):
                return [project(item) for item in value]
            return value

        shape = project(self.index.components[kind, sha])
        result = digest(shape), parameters
        self.cache[key] = result
        return result

    def profile(self, components, mode):
        result, parameters, bindings = {}, {}, []
        for kind, sha in components.items():
            shape, values = self.component(mode, kind, sha)
            result[kind] = shape
            bindings.append((kind, [parameters.setdefault(value, len(parameters)) for value in values]))
        result['literal_bindings'] = digest(bindings)
        return result


def callee_members(index):
    """Attach a direct method-access event to its call, keeping standalone reads."""
    at = {(source, tuple(op['expression_range'])): key for key, op in index.operations.items()
          for source in [key[0]] if op['kind'] == 'member_read'}
    aliases = {}
    for key, op in index.operations.items():
        if op['kind'] != 'call' or op['callee'] is None:
            continue
        member = at.get((key[0], tuple(op['callee']['range'])))
        if member is not None and index.operations[member]['name'] == op['name']:
            aliases[member] = key
    return aliases


def typed_reporting_values(sources):
    """Find Go testing.T/B parameters by import and declaration, not variable name.

    Only their use as a shared-value neighbor connector is projected away.
    Their ports, call sites, guards, effects and original graph stay available.
    """
    values=set()
    for source,(graph,_) in sources.items():
        if not graph.source['path'].endswith('.go'):
            continue
        packages=set();pending=[n for n in graph.root.named_children if n.type=='import_declaration']
        while pending:
            node=pending.pop()
            if node.type=='import_spec':
                path=node.child_by_field_name('path')
                if graph.text(path)=='"testing"':
                    name=node.child_by_field_name('name')
                    packages.add(graph.text(name) if name is not None else 'testing')
            pending.extend(node.named_children)
        for scope in graph.scopes:
            params=scope['ast'].child_by_field_name('parameters')
            if params is None:continue
            for declaration in params.named_children:
                type_node=declaration.child_by_field_name('type')
                if type_node is None:continue
                spelling=''.join(graph.text(type_node).split())
                if spelling not in {f'*{p}.{t}' for p in packages for t in ('T','B')}:
                    continue
                for name in declaration.children_by_field_name('name'):
                    values.add(f'{source}:parameter:{scope["id"]}:{graph.text(name)}')
    return values
