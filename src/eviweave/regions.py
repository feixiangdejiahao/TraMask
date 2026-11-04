"""Source regions for alignment, including literal inputs with byte provenance.

Native nodes are indexed once. Selection returns exact nodes or a contained
node set, never a containing test registration. Embedded Go and JSON receive
syntax trees only; other input languages remain opaque source material.
"""
from bisect import bisect_left, bisect_right
from collections import defaultdict
import json
from pathlib import PurePosixPath
import re

from .anchors import _parser, _call_name
from .evidence import ASSIGN, BLOCKS, CALLS, CLASS_NODES, FUNCTION_NODES, IDENTS, MEMBERS, OBS, STRINGS


FIELDS = {'pair', 'keyed_element', 'field_initializer', 'property_assignment'}
SEQUENCES = {'array', 'list', 'tuple', 'set', 'array_expression', 'tuple_expression', 'literal_value'}
OBJECTS = {'object', 'dictionary', 'struct_expression'}
COMMENTS = {'comment', 'line_comment', 'block_comment'}
ROOTS = {'module', 'program', 'source_file'}
FEATURE_KEYS = ('calls', 'members', 'keys', 'identifiers')


def _invalid_json_constant(value):
    raise ValueError('Non-JSON constant: ' + value)


def _field(node):
    return next((node.child_by_field_name(name) for name in ('attribute', 'field', 'property', 'name')
                 if node.child_by_field_name(name) is not None), None)


def _decode_literal(raw, node, suffix):
    """Decode supported literal spelling and retain each decoded byte's source.

    Unsupported spellings have an explicit reason; they are not reparsed as a
    different input format. Spans for escape sequences cover the full escape.
    """
    spelling = raw[node.start_byte:node.end_byte]
    match = re.match(rb'(?i)(?:br|rb|r|b)?(#+)?"', spelling) if suffix == '.rs' and node.type == 'raw_string_literal' else None
    raw_mode = False
    if match is not None:
        start = node.start_byte + match.end()
        end = node.end_byte - 1 - len(match[1] or b'')
        raw_mode = True
        if spelling.startswith(b'b'):
            return None, [], [start, end], 'byte_literal_text_encoding_not_modeled'
    elif spelling.startswith(b'`'):
        start, end = node.start_byte + 1, node.end_byte - 1
        raw_mode = suffix == '.go'
    else:
        match = re.match(rb'(?i)([rubf]*)("""|\x27\x27\x27|"|\x27)', spelling)
        if match is None:
            return None, [], [node.start_byte, node.end_byte], 'literal_delimiters_not_modeled'
        prefix, quote = match[1].lower(), match[2]
        start, end = node.start_byte + match.end(), node.end_byte - len(quote)
        raw_mode = b'r' in prefix
        if b'b' in prefix:
            return None, [], [start, end], 'byte_literal_text_encoding_not_modeled'
        if b'f' in prefix:
            return None, [], [start, end], 'interpolated_literal'
    if any(c.type in {'interpolation', 'template_substitution'} for c in node.named_children):
        return None, [], [start, end], 'interpolated_literal'
    if node.type == 'template_string' and node.parent is not None and node.parent.type == 'call_expression':
        return None, [], [start, end], 'tagged_template_value_not_modeled'
    output, mapping = bytearray(), []

    def append(value, a, b, identity=False):
        decoded_start = len(output)
        output.extend(value)
        if not value:
            return
        if identity and mapping and mapping[-1]['kind'] == 'identity' and mapping[-1]['source'][1] == a:
            mapping[-1]['decoded'][1] = len(output)
            mapping[-1]['source'][1] = b
        else:
            mapping.append({'decoded': [decoded_start, len(output)], 'source': [a, b],
                            'kind': 'identity' if identity else 'escape'})

    at = start
    simple = {ord('n'): b'\n', ord('r'): b'\r', ord('t'): b'\t', ord('b'): b'\b', ord('f'): b'\f',
              ord('v'): b'\v', ord('\\'): b'\\', ord('"'): b'"', ord("'"): b"'", ord('`'): b'`'}
    if suffix in {'.py', '.go'}:
        simple[ord('a')] = b'\a'
    while at < end:
        first = at
        if raw_mode or raw[at] != 92:
            at += 1
            if raw_mode and suffix == '.go' and raw[first] == 13:
                continue
            append(raw[first:at], first, at, True)
            continue
        at += 1
        char = raw[at]
        at += 1
        if char in simple:
            append(simple[char], first, at)
        elif char in {10, 13}:
            if char == 13 and at < end and raw[at] == 10:
                at += 1
            if suffix == '.rs':
                while at < end and raw[at] in b' \t\r\n':
                    at += 1
        elif char in {ord('x'), ord('u'), ord('U')}:
            if char == ord('u') and at < end and raw[at] == ord('{'):
                close = raw.index(b'}', at, end)
                digits = raw[at+1:close].replace(b'_', b'')
                at = close + 1
            else:
                width = 2 if char == ord('x') else 4 if char == ord('u') else 8
                digits = raw[at:at+width]
                at += width
            value = int(digits, 16)
            if value > 0x10FFFF:
                return None, [], [start, end], 'invalid_unicode_escape'
            if 0xD800 <= value <= 0xDFFF:
                return None, [], [start, end], 'surrogate_escape_mapping_not_modeled'
            append(bytes([value]) if suffix == '.go' and char == ord('x') else chr(value).encode(), first, at)
        elif ord('0') <= char <= ord('7'):
            while at < min(first+4, end) and ord('0') <= raw[at] <= ord('7'):
                at += 1
            value = int(raw[first+1:at], 8)
            if suffix == '.go' and value > 255:
                return None, [], [start, end], 'invalid_byte_escape'
            append(bytes([value]) if suffix == '.go' else chr(value).encode(), first, at)
        elif suffix in {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.mts', '.cts'}:
            append(bytes([char]), first, at)
        elif suffix == '.py' and char != ord('N'):
            append(raw[first:at], first, at, True)
        else:
            return None, [], [start, end], 'literal_escape_mapping_not_modeled'
    return bytes(output), mapping, [start, end], None


class RegionIndex:
    def __init__(self, graph):
        self.graph = graph
        self.regions = []
        self.issues = list(graph.issues)
        self.by_id = {}
        self._children = defaultdict(list)
        self._documents = {}
        self._nodes = {}
        self._node_regions = {}
        self._term_cache = {}
        self._feature_cache = {}
        self._fragments = {}
        self.embeddings = []
        if not graph.issues:
            self._add_document('native', graph.raw, graph.root)
            self._embedded_inputs()
        self._ordered = sorted(self.regions, key=lambda r: (r['range'][0], -r['range'][1], r['id']))
        self._starts = [r['range'][0] for r in self._ordered]
        self._max_end = []
        end = -1
        self._exact = defaultdict(list)
        for region in self._ordered:
            end = max(end, region['range'][1])
            self._max_end.append(end)
            self._exact[tuple(region['range'])].append(region)

    def _mapped_span(self, document, start, end):
        mapping = document['mapping']
        if mapping is None:
            return [start, end]
        start, end = start-document['shift'], end-document['shift']
        if start == end:
            if start == mapping[-1]['decoded'][1]:
                return [mapping[-1]['source'][1]] * 2
            segment = mapping[bisect_right(document['map_starts'], start)-1]
            position = segment['source'][0] + (start-segment['decoded'][0] if segment['kind'] == 'identity' else 0)
            return [position, position]
        first = mapping[bisect_right(document['map_starts'], start)-1]
        last = mapping[bisect_right(document['map_starts'], end-1)-1]
        a = first['source'][0] + (start-first['decoded'][0] if first['kind'] == 'identity' else 0)
        b = last['source'][0] + end-last['decoded'][0] if last['kind'] == 'identity' else last['source'][1]
        return [a, b]

    def _add_document(self, identity, raw, root, *, mapping=None, shift=0, origin=None, language=None):
        document = {'raw': raw, 'root': root, 'mapping': mapping, 'shift': shift,
                    'origin': origin, 'language': language,
                    'map_starts': [s['decoded'][0] for s in mapping] if mapping is not None else None}
        self._documents[identity] = document
        owners = {n['ast'].id: n['id'] for n in self.graph.nodes} if origin is None else {}
        todo = [(root, None, 0 if origin is None else origin['scope'], None, 0, 'root')]
        added = []
        while todo:
            node, parent, scope, statement, depth, role = todo.pop()
            if node.type in COMMENTS or node.start_byte == node.end_byte:
                continue
            if origin is None:
                statement = owners.get(node.id, statement)
                if node.id in owners:
                    scope = self.graph.nodes[statement]['scope']
            span = self._mapped_span(document, node.start_byte, node.end_byte)
            rid = f'{self.graph.source["id"]}:region:{identity}:{node.start_byte}:{node.end_byte}:{node.type}'
            annotation = node.type == 'attribute' and PurePosixPath(self.graph.source['path']).suffix == '.rs'
            kind = ('annotation' if annotation else 'field' if node.type in FIELDS else 'sequence_literal' if node.type in SEQUENCES else
                    'composite_literal' if node.type == 'composite_literal' else
                    'object_literal' if node.type in OBJECTS else 'input_string' if node.type in STRINGS else
                    'string_fragment' if 'string_content' in node.type else
                    'return' if node.type in {'return_statement', 'return_expression'} else
                    'call' if node.type in CALLS else 'member' if node.type in MEMBERS else
                    'statement' if node.type.endswith('_statement') or node.type in ASSIGN else
                    'block' if node.type in BLOCKS else 'syntax')
            features = {key: [] for key in FEATURE_KEYS}
            text = lambda n: raw[n.start_byte:n.end_byte].decode() if n is not None else ''
            if node.type in CALLS:
                name = text(node.child_by_field_name('macro')) if node.type == 'macro_invocation' else _call_name(raw, node)
                if name:
                    features['calls'].append(name)
            if node.type in MEMBERS and not annotation:
                features['members'].append(text(_field(node)))
            if node.type in FIELDS:
                key = node.child_by_field_name('key') or node.child_by_field_name('field') or node.child_by_field_name('name')
                if key is not None:
                    features['keys'].append(text(key).strip('"\''))
            if node.type in IDENTS:
                features['identifiers'].append(text(node))
            region = {'id': rid, 'range': span, 'kind': kind, 'ast_type': node.type,
                      'role': role, 'scope': scope, 'statement': statement, 'parent': parent,
                      'features': features, 'term_ref': rid, 'unknowns': [],
                      'candidate': node.type not in ROOTS | FUNCTION_NODES | CLASS_NODES,
                      'scope_boundary': node.type in FUNCTION_NODES,
                      'contains_scope_boundary': node.type in FUNCTION_NODES,
                      'observation_candidate': node.type == 'assert_statement' or any(OBS.match(n) for n in features['calls']),
                      'document': identity, 'depth': depth}
            if role == 'field_value':
                region['field_keys'] = self.by_id[parent]['features']['keys']
            if origin is not None:
                region.update({'embedded_language': language, 'origin_string': origin['id'],
                               'decoded_range': [node.start_byte-shift, node.end_byte-shift],
                               'unknowns': ['embedded_syntax_only_no_runtime_or_binding_evidence']})
            self.regions.append(region)
            self.by_id[rid] = region
            self._nodes[rid] = (identity, node)
            self._node_regions[identity, node.id] = region
            self._children[parent].append(rid)
            added.append(region)
            children = []
            counts = defaultdict(int)
            for index, child in enumerate(node.children):
                if not child.is_named or child.type in COMMENTS:
                    continue
                field = node.field_name_for_child(index) or 'item'
                child_role = f'{field}:{counts[field]}'
                counts[field] += 1
                if node.type in FIELDS and field == 'value':
                    child_role = 'field_value'
                child_scope = scope
                if origin is None and node.id in self.graph.scope_nodes and child == node.child_by_field_name('body'):
                    child_scope = self.graph.scope_nodes[node.id]
                children.append((child, rid, child_scope, statement, depth+1, child_role))
            todo.extend(reversed(children))
        for region in reversed(added):
            children = [self.by_id[rid] for rid in self._children[region['id']]]
            region['contains_scope_boundary'] |= any(c['contains_scope_boundary'] for c in children)
            region['observation_candidate'] |= any(c['observation_candidate'] for c in children if not c['scope_boundary'])
            if region['kind'] == 'block' and region['observation_candidate']:
                region['kind'] = 'observation_block'
        return added[0]

    def _embedded_inputs(self):
        suffix = PurePosixPath(self.graph.source['path']).suffix
        strings = [r for r in self.regions if r['kind'] == 'input_string']
        for origin in strings:
            _, node = self._nodes[origin['id']]
            decoded, mapping, content_range, reason = _decode_literal(self.graph.raw, node, suffix)
            record = {'id': origin['id'], 'source_range': content_range, 'status': 'opaque',
                      'language': None, 'offset_map': [], 'reason': reason or 'input_language_not_parsed'}
            origin['input'] = record
            self.embeddings.append(record)
            if decoded is None or not decoded.strip():
                continue
            try:
                decoded.decode()
            except UnicodeDecodeError as error:
                record['reason'] = 'literal_is_not_utf8_text: ' + str(error)
                continue
            language, shift = None, 0
            parse_raw = decoded
            if re.match(rb'\s*package\s+[A-Za-z_]\w*', decoded):
                language = 'go'
                root = _parser('.go').parse(decoded).root_node
            elif decoded.lstrip().startswith((b'{', b'[')):
                try:
                    json.loads(decoded, parse_constant=_invalid_json_constant)
                except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                    record['reason'] = 'not_valid_json: ' + str(error)
                    continue
                language, shift = 'json', 1
                parse_raw = b'(' + decoded + b')'
                parsed = _parser('.ts').parse(parse_raw).root_node
                root = parsed.named_children[0].named_children[0].named_children[0]
            else:
                continue
            if root.has_error:
                record['reason'] = 'embedded_parse_error'
                record['candidate_language'] = language
                continue
            record.update({'status': 'parsed_syntax', 'language': language, 'reason': None, 'offset_map': mapping})
            embedded = self._add_document('embedded:' + str(node.start_byte), parse_raw, root,
                                          mapping=mapping, shift=shift, origin=origin, language=language)
            record['root'] = embedded['id']

    def features(self, region):
        """Aggregate on request, excluding bodies of nested function values."""
        rid = region if isinstance(region, str) else region['id']
        if rid in self._fragments:
            return self._fragments[rid]['features']
        if rid in self._feature_cache:
            return self._feature_cache[rid]
        result = {key: set() for key in FEATURE_KEYS}
        todo = [rid]
        while todo:
            current = self.by_id[todo.pop()]
            if current['id'] != rid and current['scope_boundary']:
                continue
            for key in FEATURE_KEYS:
                result[key].update(current['features'][key])
            todo.extend(self._children[current['id']])
        value = {key: sorted(values) for key, values in result.items()}
        self._feature_cache[rid] = value
        return value

    def term(self, region):
        """Return shared plain-dict terms with original-source byte coordinates."""
        rid = region if isinstance(region, str) else region['id']
        if rid in self._fragments:
            fragment = self._fragments[rid]
            a, b = fragment['range']
            return {'kind': 'source_interval', 'value': self.graph.raw[a:b].decode(), 'span': [a, b], 'children': []}
        document_id, root = self._nodes[rid]
        document = self._documents[document_id]
        raw = document['raw']
        pending = [(root, False)]
        while pending:
            node, ready = pending.pop()
            key = document_id, node.id
            if key in self._term_cache:
                continue
            children = [c for c in node.children if c.type not in COMMENTS]
            embedded = (self._node_regions[key]['input'] if document['origin'] is None and node.type in STRINGS else None)
            if embedded is not None and embedded['status'] == 'parsed_syntax':
                term = {'kind': 'embedded_input:' + embedded['language'], 'value': '',
                        'span': [node.start_byte, node.end_byte],
                        'children': [['program:0', self.term(embedded['root'])]]}
            elif node.type in STRINGS or not children:
                value = raw[node.start_byte:node.end_byte].decode()
                kind = node.type
                parent = node.parent
                fixed = parent is not None and (
                    parent.type in MEMBERS and _field(parent) == node or
                    parent.type in CALLS and parent.child_by_field_name('function') == node or
                    parent.type in FIELDS | {'keyword_argument'} and node in
                    [parent.child_by_field_name(field) for field in ('name', 'key', 'field')])
                if node.type in IDENTS and not fixed and document['origin'] is None:
                    scope = self._node_regions[document_id, node.id]['scope']
                    binding = self.graph._binding(scope, value)
                    kind, value = 'reference', str(binding[0]) + ':' + binding[1]
                term = {'kind': kind, 'value': value, 'span': self._mapped_span(document, node.start_byte, node.end_byte), 'children': []}
            elif not ready:
                pending.append((node, True))
                pending.extend((c, False) for c in reversed(children))
                continue
            else:
                values, counts = [], defaultdict(int)
                for index, child in enumerate(node.children):
                    if child.type in COMMENTS:
                        continue
                    role = node.field_name_for_child(index) or ('named' if child.is_named else child.type)
                    position = f'{role}:{counts[role]}'
                    counts[role] += 1
                    values.append([position, self._term_cache[document_id, child.id]])
                term = {'kind': node.type, 'value': '', 'span': self._mapped_span(document, node.start_byte, node.end_byte), 'children': values}
            self._term_cache[key] = term
        return self._term_cache[document_id, root.id]

    def select(self, start, end):
        """Preserve a query interval and report its exact/contained AST regions."""
        exact = self._exact[start, end]
        at = bisect_right(self._starts, start)-1
        covering = []
        while at >= 0 and self._max_end[at] >= end:
            region = self._ordered[at]
            if region['range'][0] <= start and end <= region['range'][1]:
                covering.append(region)
            at -= 1
        covering.sort(key=lambda r: (r['range'][1]-r['range'][0], -r['depth'], r['id']))
        candidates = [r for r in self._ordered[bisect_left(self._starts, start):bisect_left(self._starts, end)]
                      if r['range'][1] <= end]
        candidate_ids = {r['id'] for r in candidates}
        contained = [r for r in candidates if r['parent'] not in candidate_ids]
        # Embedded syntax wins only within a decoded string's actual content.
        embedded = [r for r in exact if 'embedded_language' in r]
        interpolations = [r for r in covering if r['document'] == 'native'
                          and r['ast_type'] in {'interpolation', 'template_substitution'}]
        # An opaque template value still contains actual host expressions.
        # Only the containing string is bypassed; a string literal inside the
        # interpolation keeps its own opaque content boundary.
        opaque = next((r for r in covering if r['document'] == 'native' and r['kind'] == 'input_string' and r['input']['status'] == 'opaque'
                       and r['input']['source_range'][0] <= start and end <= r['input']['source_range'][1]
                       and not any(r['range'][0] <= part['range'][0] and part['range'][1] <= r['range'][1]
                                   for part in interpolations)), None)
        if opaque is not None:
            selected = [self._fragment(start, end, opaque)]
            status = 'opaque'
        elif exact:
            chosen = max(embedded or exact, key=lambda r: r['depth'])
            spelling = self.graph.raw[start:end].strip()
            if chosen['ast_type'] in ROOTS | BLOCKS and not (spelling.startswith(b'{') and spelling.endswith(b'}')):
                selected, pending = [], list(reversed(self._children[chosen['id']]))
                while pending:
                    child = self.by_id[pending.pop()]
                    if child['ast_type'] in ROOTS | BLOCKS:
                        pending.extend(reversed(self._children[child['id']]))
                    else:
                        selected.append(child)
                status = 'node_set'
            else:
                selected = [chosen]
                status = 'exact'
        else:
            if contained:
                selected = contained
                status = 'node_set'
            else:
                selected = [self._fragment(start, end, covering[0] if covering else None)]
                status = 'fragment'
        return {'range': [start, end], 'status': status, 'selected': selected,
                'exact': list(exact), 'covering': covering, 'contained': contained}

    def _fragment(self, start, end, parent):
        rid = f'{self.graph.source["id"]}:fragment:{start}:{end}'
        if rid not in self._fragments:
            self._fragments[rid] = {'id': rid, 'range': [start, end], 'kind': 'opaque_fragment',
                                   'ast_type': 'source_interval', 'role': 'source_fragment',
                                   'scope': parent['scope'] if parent else 0, 'statement': parent['statement'] if parent else None,
                                   'parent': parent['id'] if parent else None, 'features': {key: [] for key in FEATURE_KEYS},
                                   'unknowns': ['fragment_has_no_parsed_behavior'], 'term_ref': rid,
                                   'candidate': False, 'contains_scope_boundary': False}
        return self._fragments[rid]
