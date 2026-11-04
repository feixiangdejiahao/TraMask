"""Role-aligned local differences, with concrete bindings kept as domains.

The same parameterised difference can share comparison and planning work.
Its concrete bindings are alternatives, not proved equivalent executions.
"""
from itertools import combinations

from .alignment import anti_unify, term_key
from .alignment_templates import NUMBERS
from .evidence import CALLS, FUNCTION_NODES, MEMBERS, STRINGS
from .port_admission import literal_number
from .regions import OBJECTS, SEQUENCES
from .value_recipes import PRIMITIVES, UNARY
from .relational_alignment import digest, ports


class BehaviorDeltaIndex:
    def __init__(self, port_index):
        self.index = port_index
        self.cache = {}

    def facets(self, record):
        """Address facts by root port instead of hashing the entire test."""
        key = record['key']
        cache_key = key, tuple(sorted(record['roles'], key=repr))
        if cache_key in self.cache:
            return self.cache[cache_key]
        source = key[0]
        op = self.index.operations[key]
        values = {}

        def put(address, exact, shape=None):
            values[address] = (digest(exact), digest(exact if shape is None else shape))

        resolved, names, topology = {}, {}, []
        for p in ports(op):
            role = p['role']
            cells = [p['binding']] + [read['binding'] for read in p['reads']]
            topology.append((role,[names.setdefault(tuple(cell),len(names)) if cell is not None else None
                                   for cell in cells]))
            put(('port', role), self.index._syntax(source, p['range'])[0],
                self.index._syntax(source, p['range'])[1])
            # Keep the value reaching this particular port, including may
            # alternatives. A producer belonging to another port cannot align
            # merely because it occurs somewhere in the same slice.
            definitions = set()
            starts = set(p['definition_versions'])
            starts.update(d for read in p['reads'] for d in read['definition_versions'])
            starts.update(before[1] for before, edge in self.index.incoming[key]
                          if edge['evidence'].get('port') == role)
            for identity in starts:
                reached, _ = self.index.construction((source, identity))
                definitions.update(reached)
            constructors = []
            for dkey in sorted(definitions):
                d = self.index.definitions[dkey]
                if d['value_range'] is not None:
                    exact, shape = self.index._syntax(source, d['value_range'])
                    constructors.append((d['value_kind'], exact, shape))
            put(('construction', role), sorted((k, e) for k, e, _ in constructors),
                sorted((k, t) for k, _, t in constructors))
            direct = [self.index.definitions[source, identity]['value_range']
                      for identity in p['definition_versions']]
            if len(direct) == 1 and direct[0] is not None:
                resolved[role] = direct[0]
            else:
                resolved[role] = p['range']
        # Correspondences are rooted paths: input/output direction, receiving
        # port and producer/consumer descriptor. Different endpoint relations
        # become differences rather than a second admission filter.
        for witness in record['roles']:
            if len(witness) == 4:
                _, direction, role, descriptor = witness
                put(('connection', direction, role, *descriptor), True)
            else:
                put(('field', witness[2]), True)
        for a, b, relation in record['identity_relations']:
            put(('identity', a, b), relation)
        for a, b, relation in record['value_relations']:
            put(('numeric_relation', a, b), relation)
        for a, b in combinations(resolved, 2):
            # Equal syntax is only a content relation for reference-free
            # values. References need their reaching definitions and identity.
            ta = self.index.terms[source].term(resolved[a])
            tb = self.index.terms[source].term(resolved[b])
            pending = [ta, tb]; references = False
            while pending:
                term = pending.pop()
                references |= term.kind in CALLS | MEMBERS | FUNCTION_NODES | {'reference'}
                pending.extend(child for _, child in term.children)
            if not references:
                x = self.index._syntax(source, resolved[a])[0]
                y = self.index._syntax(source, resolved[b])[0]
                put(('content_relation', a, b), 'equal' if x == y else 'different')
        put(('lexical_topology',), topology)
        guards = [(g['polarity'], *self.index._syntax(source, g['range'])) for g in op['guards']]
        put(('condition',), [(p, e) for p, e, _ in guards], [(p, t) for p, _, t in guards])
        put(('phase',), [(f['kind'], f.get('branch'), f.get('mode')) for f in op['frames']])
        put(('consumer_state',), sorted({(self.index.descriptor(c), self.index.descriptor(o), *rest)
                                         for c, o, *rest in record['consumer_state']}, key=repr))
        self.cache[cache_key] = values
        return values

    def difference(self, left, right):
        """Joint edit bundle; do not split mutually dependent edits apart."""
        a, b = self.facets(left), self.facets(right)
        changed = [address for address in sorted(a.keys() | b.keys(), key=repr) if a.get(address) != b.get(address)]
        exact = [(address, a.get(address), b.get(address)) for address in changed]
        # Bindings record whether changes at multiple roles use equal payloads.
        # Numeric values with a different ordering are already separate facets.
        names = {}
        topology = []
        schema = []
        for address in changed:
            old, new = a.get(address), b.get(address)
            schema.append((address, old[1] if old is not None else None,
                           new[1] if new is not None else None))
            topology.append(tuple(names.setdefault(v[0], len(names)) if v is not None else None
                                  for v in (old, new)))
        return {'addresses': changed, 'exact': digest(exact),
                'schema': digest((schema, topology)), 'parameter_only': bool(changed) and
                all(a.get(k) is not None and b.get(k) is not None and a[k][1] == b[k][1] for k in changed)}

    def syntax_difference(self, left_key, right_key):
        """Source edits at corresponding root inputs and immediate definitions."""
        index = self.index
        a, b = [index.operations[k] for k in (left_key, right_key)]
        aa, bb = [{p['role']: p for p in ports(op)} for op in (a, b)]
        edits = []
        for role in sorted(aa.keys() & bb.keys()):
            spans = [p[role]['range'] for p in (aa, bb)]
            for n, (key, pp) in enumerate(zip((left_key, right_key), (aa, bb))):
                defs = pp[role]['definition_versions']
                if len(defs) == 1:
                    span = index.definitions[key[0], defs[0]]['value_range']
                    if span is not None:
                        spans[n] = span
            terms = [index.terms[key[0]].term(span) for key, span in zip((left_key, right_key), spans)]
            edits.append({'role':role, 'ranges':spans, **anti_unify(*terms)})
        return edits

    def edit_schema(self, left_key, right_key):
        """Parameterise closed replacement subtrees after structural alignment.

        Fields/selectors keep their spelling. Distinct allocations and equality
        of payloads are separate constraints; every concrete payload is kept.
        """
        edits = self.syntax_difference(left_key, right_key)
        rows, bindings, numbers, allocations = [], [], [], []
        names = {}
        for edit in edits:
            for hole in edit['holes']:
                row, values = [], []
                for key, span in zip((left_key,right_key),(hole['left'],hole['right'])):
                    if span is None:
                        row.append(None); values.append(None)
                        continue
                    term = self.index.terms[key[0]].term(span)
                    pending = [term]; closed = True
                    while pending:
                        node = pending.pop()
                        closed &= node.kind not in CALLS | FUNCTION_NODES | MEMBERS | {'reference'}
                        pending.extend(child for _,child in node.children)
                    selector = any(role.startswith(('index:', 'subscript:', 'slice:', 'key:', 'field:',
                                                     'attribute:', 'property:', 'function:')) for role in hole['role'])
                    category = ('object' if term.kind in OBJECTS else 'sequence' if term.kind in SEQUENCES else
                                'opaque_string' if term.kind in STRINGS else term.kind)
                    exact = digest(term_key(term))
                    literal = term.kind in OBJECTS | SEQUENCES | NUMBERS | STRINGS | PRIMITIVES
                    literal |= term.kind in UNARY and literal_number(term) is not None
                    parameter = closed and literal and not selector
                    row.append(('parameter',category) if parameter else ('syntax',exact))
                    values.append(exact)
                    bindings.append({'source':key[0],'range':span,'kind':category,'exact':exact})
                    number = literal_number(term)
                    if number is not None:
                        numbers.append((len(rows),len(row)-1,number))
                    if parameter and term.kind in OBJECTS | SEQUENCES:
                        allocations.append((len(rows),len(row)-1))
                topology = tuple(names.setdefault(v,len(names)) if v is not None else None for v in values)
                rows.append((edit['role'],hole['role'],row,topology))
        numeric = [(a[:2],b[:2],'equal' if a[2]==b[2] else 'less' if a[2]<b[2] else 'greater')
                   for a,b in combinations(numbers,2)]
        return {'schema':digest((rows,numeric,allocations)), 'holes':rows,
                'numeric_relations':numeric,'fresh_value_occurrences':allocations,'bindings':bindings}
