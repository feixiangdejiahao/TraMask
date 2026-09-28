"""Bounded read/write relation cells inside source SQL string inputs.

The deliberately small SQL grammar accepts one SELECT or UPDATE over one
explicit table. Numeric comparisons supply fields and boundary constants;
UPDATE source text supplies the carrier and row filter. Identifiers never come
from a schema, task description, model, or execution result. Unsupported SQL
is skipped rather than guessed. These are input hypotheses, not oracle proofs.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict, deque
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, localcontext
import re

from anchor_retrieval.syntax import FUNCTIONS, Source, child, literal, walk
from generic_composition.corpus import source_text
from generic_composition.engine import contained, expanded_donors, expected_only, slot_key, stable_id
from .structured_ports import carrier_ports, structural_slot_key


@dataclass(frozen=True)
class EmbeddedRelationBudget:
    max_candidates: int = 128
    max_pool: int = 1024
    max_donors: int = 512
    max_reads_per_write: int = 16
    max_read_sources: int = 8
    max_predicates: int = 16
    max_assignment_sources: int = 8
    max_string_bytes: int = 4000
    max_tokens: int = 512
    top_k: int = 10
    boundary_offsets: tuple[int, ...] = (0, -1, 1)


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class Identifier:
    tokens: tuple[Token, ...]

    @property
    def key(self):
        # Quoted and unquoted spellings are not equated across SQL dialects.
        return tuple(t.text if t.kind == 'identifier' else t.text.lower() for t in self.tokens)

    @property
    def leaf(self):
        return Identifier(self.tokens[-1:])


@dataclass(frozen=True)
class Predicate:
    field: Identifier
    operator: str
    threshold: Decimal
    literal: str
    start: int
    end: int


@dataclass(frozen=True)
class Assignment:
    field: Identifier
    start: int
    end: int
    value_start: int
    value_end: int
    numeric: Decimal | None


@dataclass(frozen=True)
class SQLProgram:
    text: str
    kind: str
    table: Identifier | None
    alias: Identifier | None
    predicates: tuple[Predicate, ...] = ()
    assignments: tuple[Assignment, ...] = ()
    where_start: int | None = None

    @property
    def where_text(self):
        return self.text[self.where_start:] if self.where_start is not None else ''


_NUMBER = re.compile(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
_WORD = re.compile(r'[A-Za-z_][A-Za-z_0-9$]*')
_COMPARATORS = {'=', '==', '!=', '<>', '<', '<=', '>', '>='}
_REVERSE = {'=': '=', '==': '==', '!=': '!=', '<>': '<>', '<': '>', '<=': '>=', '>': '<', '>=': '<='}
_INVERT = {'=': '!=', '==': '!=', '!=': '=', '<>': '=', '<': '>=', '<=': '>', '>': '<=', '>=': '<'}
_TAIL_CLAUSES = {'GROUP', 'HAVING', 'ORDER', 'LIMIT', 'OFFSET', 'UNION', 'INTERSECT', 'EXCEPT', 'RETURNING', 'WINDOW'}


def _tokens(text, limit):
    """A lossless-position lexer; strings/comments cannot become identifiers."""
    result, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        if text.startswith('--', i):
            end = text.find('\n', i + 2)
            i = len(text) if end < 0 else end
            continue
        if text.startswith('/*', i):
            end = text.find('*/', i + 2)
            if end < 0 or '/*' in text[i + 2:end]:
                return None
            i = end + 2
            continue
        start = i
        if text[i] in "'\"`[":
            opening = text[i]
            closing = ']' if opening == '[' else opening
            i += 1
            while i < len(text):
                if text[i] == closing:
                    if i + 1 < len(text) and text[i + 1] == closing:
                        i += 2
                        continue
                    i += 1
                    break
                # SQL backslash escape semantics vary by dialect.
                if text[i] == '\\':
                    return None
                i += 1
            else:
                return None
            kind = 'string' if opening == "'" else 'identifier'
        elif match := _NUMBER.match(text, i):
            i, kind = match.end(), 'number'
        elif match := _WORD.match(text, i):
            i, kind = match.end(), 'word'
        elif text[i] in ':@$?' and (match := re.match(r'(?:[:@$][A-Za-z_0-9]+|\?[0-9]*)', text[i:])):
            i, kind = i + match.end(), 'parameter'
        elif text[i:i + 2] in {'<=', '>=', '<>', '!=', '==', '||'}:
            i, kind = i + 2, 'operator'
        elif text[i] in '=<>+-*/%(),.;':
            i, kind = i + 1, 'operator'
        else:
            return None
        result.append(Token(kind, text[start:i], start, i))
        if len(result) > limit:
            return None
    if result and result[-1].text == ';':
        result.pop()
    if any(t.text == ';' for t in result):
        return None
    return result


def _keyword(token, text):
    return token.kind == 'word' and token.text.upper() == text


def _top_level(tokens):
    depth = 0
    for i, token in enumerate(tokens):
        if token.text == '(':
            depth += 1
        elif token.text == ')':
            depth -= 1
            if depth < 0:
                raise ValueError('unbalanced_parentheses')
        elif depth == 0:
            yield i, token
    if depth:
        raise ValueError('unbalanced_parentheses')


def _identifier(tokens):
    if not tokens or len(tokens) % 2 != 1:
        return None
    if any(t.kind not in {'word', 'identifier'} for t in tokens[::2]):
        return None
    if any(t.text != '.' for t in tokens[1::2]):
        return None
    return Identifier(tuple(tokens[::2]))


def _table(tokens):
    alias = None
    if len(tokens) >= 3 and _keyword(tokens[-2], 'AS'):
        alias, tokens = _identifier(tokens[-1:]), tokens[:-2]
    elif len(tokens) >= 2 and tokens[-1].kind in {'word', 'identifier'} and tokens[-2].text != '.':
        alias, tokens = _identifier(tokens[-1:]), tokens[:-1]
    table = _identifier(tokens)
    return (table, alias) if table is not None else (None, None)


def _numeric(tokens):
    if len(tokens) == 1 and tokens[0].kind == 'number':
        text = tokens[0].text
    elif len(tokens) == 2 and tokens[0].text in {'+', '-'} and tokens[1].kind == 'number':
        text = tokens[0].text + tokens[1].text
    else:
        return None
    try:
        number = Decimal(text)
        # Avoid unbounded exponent expansion and precision-dependent offsets.
        return number if number.is_finite() and abs(number.adjusted()) <= 100 and len(number.as_tuple().digits) <= 100 else None
    except InvalidOperation:
        return None


def _belongs(field, table, alias):
    return len(field.tokens) == 1 or table is not None and field.key[:-1] in {table.key, table.leaf.key, alias.key if alias else ()}


def _table_key(program):
    return program.table.key if program.table is not None else None


def _alignment_keys(donor):
    keys = {('actual', *structural_slot_key(p)) for p in donor['aligned_ports']}
    for port in donor['aligned_ports']:
        path = structural_slot_key(port)[-1]
        keys.update(('formal', b['function_id'], b['parameter_index'], path) for b in port.get('formal_slots', []))
    return keys


def _neutral_predicate(tokens):
    """Recognize comparison syntax without assigning function semantics.

    Function operands remain opaque; their spelling never supplies a writable
    field. This only preserves a source input as a possible predicate carrier.
    """
    if not tokens:
        return False
    try:
        top = list(_top_level(tokens))
    except ValueError:
        return False
    if not top and tokens[0].text == '(' and tokens[-1].text == ')':
        return _neutral_predicate(tokens[1:-1])
    if _keyword(tokens[0], 'NOT'):
        return _neutral_predicate(tokens[1:])
    splits = [i for i, t in top if _keyword(t, 'AND') or _keyword(t, 'OR')]
    if splits:
        previous = 0
        for end in [*splits, len(tokens)]:
            if not _neutral_predicate(tokens[previous:end]):
                return False
            previous = end + 1
        return True
    comparisons = [i for i, t in top if t.text in _COMPARATORS]
    if len(comparisons) != 1:
        return False
    def scalar(parts, depth=0):
        if not parts or depth > 8:
            return False
        if _identifier(parts) is not None or _numeric(parts) is not None or len(parts) == 1 and parts[0].kind in {'string', 'parameter'}:
            return True
        if len(parts) >= 3 and parts[1].text == '(' and parts[-1].text == ')' and _identifier(parts[:1]):
            inside = parts[2:-1]
            if len(inside) == 1 and inside[0].text == '*':
                return True
            try:
                commas = [i for i, t in _top_level(inside) if t.text == ',']
            except ValueError:
                return False
            previous = 0
            for end in [*commas, len(inside)]:
                if not scalar(inside[previous:end], depth + 1):
                    return False
                previous = end + 1
            return True
        return False
    i = comparisons[0]
    return scalar(tokens[:i]) and scalar(tokens[i + 1:])


def _predicates(tokens, text, table, alias):
    """Accept Boolean trees of simple comparisons, retaining numeric leaves.

    Truth metadata applies to a comparison leaf, never the complete WHERE.
    Non-numeric leaves are accepted only as field/literal comparisons.
    """
    if not tokens:
        raise ValueError('empty_predicate')
    top = list(_top_level(tokens))
    if not top and tokens[0].text == '(' and tokens[-1].text == ')':
        # Two adjacent parenthesized expressions are not one outer group.
        depth = 0
        for token in tokens[:-1]:
            depth += (token.text == '(') - (token.text == ')')
            if depth == 0:
                raise ValueError('missing_boolean_operator')
        return _predicates(tokens[1:-1], text, table, alias)
    for operator in ('OR', 'AND'):
        splits = [i for i, token in top if _keyword(token, operator)]
        if splits:
            result, previous = [], 0
            for end in [*splits, len(tokens)]:
                result.extend(_predicates(tokens[previous:end], text, table, alias))
                previous = end + 1
            return result
    if _keyword(tokens[0], 'NOT'):
        return [Predicate(p.field, _INVERT[p.operator], p.threshold, p.literal, tokens[0].start, p.end)
                for p in _predicates(tokens[1:], text, table, alias)]
    comparisons = [(i, t) for i, t in top if t.text in _COMPARATORS]
    if len(comparisons) != 1:
        raise ValueError('unsupported_predicate')
    i, operator = comparisons[0]
    left, right = tokens[:i], tokens[i + 1:]
    if not left or not right:
        raise ValueError('missing_operand')
    field, number = _identifier(left), _numeric(right)
    literal_tokens = right
    if field is None or number is None:
        field, number = _identifier(right), _numeric(left)
        literal_tokens = left
        op = _REVERSE[operator.text]
    else:
        op = operator.text
    if field is not None and number is not None:
        if not _belongs(field, table, alias):
            raise ValueError('unresolved_field_qualifier')
        return [Predicate(field, op, number, text[literal_tokens[0].start:literal_tokens[-1].end],
                          tokens[0].start, tokens[-1].end)]
    def scalar(parts):
        field = _identifier(parts)
        return (field is not None and _belongs(field, table, alias) or _numeric(parts) is not None
                or len(parts) == 1 and parts[0].kind in {'string', 'parameter'})
    if scalar(left) and scalar(right):
        return []
    raise ValueError('unsupported_comparison_operands')


def parse_sql_program(text: str, *, max_tokens=512) -> SQLProgram | None:
    """Parse the documented subset without executing SQL or inferring a schema."""
    tokens = _tokens(text, max_tokens)
    if not tokens:
        return None
    try:
        top = list(_top_level(tokens))
        if any(t.kind == 'word' and t.text.upper() in _TAIL_CLAUSES for _, t in top):
            return None
        if any(t.kind == 'word' and t.text.upper() in {'SELECT', 'UPDATE', 'DELETE', 'INSERT', 'WITH'}
               for t in tokens[1:]):
            return None
        where = [i for i, t in top if _keyword(t, 'WHERE')]
        if len(where) > 1:
            return None
        end = where[0] if where else len(tokens)
        if where and end + 1 == len(tokens):
            return None
        where_start = tokens[end].start if where else None
        if _keyword(tokens[0], 'SELECT'):
            froms = [i for i, t in top if _keyword(t, 'FROM')]
            if len(froms) != 1 or froms[0] <= 1 or froms[0] >= end:
                return None
            table, alias = _table(tokens[froms[0] + 1:end])
            if table is None:
                return None
            predicates = _predicates(tokens[end + 1:], text, table, alias) if where else []
            return SQLProgram(text, 'select', table, alias, tuple(predicates), where_start=where_start)
        if _keyword(tokens[0], 'UPDATE'):
            sets = [i for i, t in top if _keyword(t, 'SET')]
            if len(sets) != 1 or not 1 < sets[0] < end - 1:
                return None
            table, alias = _table(tokens[1:sets[0]])
            if table is None:
                return None
            assignments, seen = [], set()
            parts = tokens[sets[0] + 1:end]
            previous = 0
            for stop in [*[i for i, t in _top_level(parts) if t.text == ','], len(parts)]:
                piece = parts[previous:stop]
                previous = stop + 1
                equals = [i for i, t in _top_level(piece) if t.text == '=']
                if len(equals) != 1:
                    return None
                at = equals[0]
                field, value = _identifier(piece[:at]), piece[at + 1:]
                if field is None or len(field.tokens) != 1 or field.key in seen or not value:
                    return None
                seen.add(field.key)
                assignments.append(Assignment(field, piece[0].start, piece[-1].end,
                                              value[0].start, value[-1].end, _numeric(value)))
            return SQLProgram(text, 'update', table, alias, assignments=tuple(assignments), where_start=where_start)
    except (ValueError, IndexError, RecursionError):
        return None
    return None


def format_source_string(value: str, language: str, original: str) -> str | None:
    """Keep the original host delimiter/prefix; reject unrepresentable raw text."""
    if language == 'python':
        match = re.match(r'''(?i)^([ru]*)("""|''' + "'''" + r'''|"|')''', original)
        if not match or not original.endswith(match[2]):
            return None
        prefix, quote = match.groups()
        if 'r' in prefix.lower():
            result = prefix + quote + value + quote
        else:
            body = value.replace('\\', '\\\\').replace(quote[0], '\\' + quote[0])
            body = body.replace('\x00', '\\x00').replace('\r', '\\r')
            if len(quote) == 1:
                body = body.replace('\n', '\\n')
            result = prefix + quote + body + quote
        try:
            return result if ast.literal_eval(result) == value else None
        except (SyntaxError, ValueError):
            return None
    if language not in {'go', 'typescript'} or not original or original[0] not in {'"', "'", '`'}:
        return None
    quote = original[0]
    if not original.endswith(quote) or language == 'go' and quote == "'":
        return None
    if language == 'go' and quote == '`':
        return '`' + value + '`' if '`' not in value and '\r' not in value else None
    body = value.replace('\\', '\\\\').replace(quote, '\\' + quote)
    for before, after in [('\n', '\\n'), ('\r', '\\r'), ('\t', '\\t'), ('\b', '\\b'), ('\f', '\\f'), ('\x00', '\\x00')]:
        body = body.replace(before, after)
    if quote == '`':
        body = body.replace('${', '\\${')
    return quote + body + quote


def _source_string(donor, language):
    """Decode a bounded host literal subset, rejecting dialect escape ambiguity."""
    text = donor['text']
    if language == 'go' and text.startswith('`') and text.endswith('`'):
        return text[1:-1].replace('\r', '')
    if language == 'typescript' and text.startswith('`'):
        # The shared frontend treats template content as raw. Do not silently
        # use that approximation for escaped JavaScript template contents.
        return text[1:-1] if text.endswith('`') and '\\' not in text and '${' not in text else None
    if language == 'typescript' and re.search(r'\\(?![\\\'"bfnrtv0]|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4})', text):
        return None
    if language == 'go':
        # Python decodes byte escapes as code points; Go stores bytes. Accept
        # the common ASCII intersection instead of confusing these encodings.
        for pattern, base in [(r'\\x([0-9a-fA-F]{2})', 16), (r'\\([0-7]{3})', 8)]:
            if any(int(match[1], base) > 127 for match in re.finditer(pattern, text)):
                return None
    try:
        value = ast.literal_eval(text)
        return value if isinstance(value, str) else None
    except (ValueError, SyntaxError):
        return None


def _truth(value, predicate):
    threshold = predicate.threshold
    return {'=': value == threshold, '==': value == threshold, '!=': value != threshold,
            '<>': value != threshold, '<': value < threshold, '<=': value <= threshold,
            '>': value > threshold, '>=': value >= threshold}[predicate.operator]


def _boundary(predicate, offset):
    if offset == 0:
        return predicate.literal, predicate.threshold
    with localcontext() as context:
        context.prec = 210
        number = predicate.threshold + offset
    return format(number, 'f'), number


def _position(item):
    span = item.get('span', item)
    return span['path'], span['start_byte'], span['end_byte']


def _source_fact(donor, program, start, end, role):
    return {'donor_id': donor['id'], 'test_id': donor['test_id'], 'span': donor['span'],
            'role': role, 'decoded_string_range': [start, end], 'text': program.text[start:end],
            'source_input_also_feeds_expected': bool(donor.get('oracle_dependency')),
            'range_unit': 'unicode_codepoints_in_decoded_string'}


def _read_pairs(recipient_id, reads, budget):
    """Local predicates first; then bounded same-slot source query transfers."""
    recipients = reads[recipient_id][:budget.max_reads_per_write]
    for read, query in recipients:
        yield read, query, read, query
    all_reads = [pair for members in reads.values() for pair in members]
    for read, query in recipients:
        if read.get('oracle_dependency') or read.get('role') == 'expected':
            continue  # Keep shared input/expected dependencies immutable.
        aligned = _alignment_keys(read)
        seen, count = {query.text}, 0
        for origin, source_query in all_reads:
            if origin['test_id'] == recipient_id or source_query.text in seen or not source_query.predicates:
                continue
            if _table_key(query) != _table_key(source_query):
                continue
            if read.get('embedded_form', 'statement') != origin.get('embedded_form', 'statement'):
                continue
            if not aligned.intersection(_alignment_keys(origin)):
                continue
            if count >= budget.max_read_sources:
                break
            seen.add(source_query.text)
            count += 1
            yield read, query, origin, source_query


def _sql_templates(sources, frontend):
    """Single-formal string templates from resolved production declarations."""
    templates = defaultdict(list)
    if not frontend:
        return templates
    from .transforms import _node_for
    reachable = {b['function_id'] for call in frontend.get('calls', []) + frontend.get('production_calls', [])
                 for b in call.get('argument_bindings', [])}
    for function in frontend.get('functions', []):
        if function.get('test') or function['span']['path'] not in sources or function['id'] not in reachable:
            continue
        source = sources[function['span']['path']]
        body = _node_for(source, {'span': function['body_span']})
        if body is None:
            continue
        parameters = {p['name']: p['index'] for p in function['parameters'] if p.get('name')}
        def pieces(node):
            if node is None:
                return None
            try:
                value = literal(source.text(node))
                if isinstance(value, str):
                    return [value]
            except ValueError:
                pass
            if node.type == 'identifier' and source.text(node) in parameters:
                return [parameters[source.text(node)]]
            if node.type == 'parenthesized_expression' and len(node.named_children) == 1:
                return pieces(node.named_children[0])
            if node.type in {'binary_expression', 'binary_operator'} and source.text(child(node, 'operator')) == '+':
                left, right = pieces(child(node, 'left')), pieces(child(node, 'right'))
                return left + right if left is not None and right is not None else None
            # A plain f-string interpolation is a source-owned string hole.
            if source.language == 'python' and node.type == 'string':
                try:
                    expression = ast.parse(source.text(node), mode='eval').body
                except (SyntaxError, ValueError):
                    return None
                if isinstance(expression, ast.JoinedStr):
                    result = []
                    for item in expression.values:
                        if isinstance(item, ast.Constant) and isinstance(item.value, str):
                            result.append(item.value)
                        elif (isinstance(item, ast.FormattedValue) and isinstance(item.value, ast.Name)
                              and item.value.id in parameters and item.conversion == -1 and item.format_spec is None):
                            result.append(parameters[item.value.id])
                        else:
                            return None
                    return result
            return None
        for node in walk(body):
            if node.type not in {'binary_expression', 'binary_operator', 'string'}:
                continue
            parent = node.parent
            nested = False
            while parent is not None and parent.start_byte >= function['body_span']['start_byte']:
                if parent.type in FUNCTIONS | {'arrow_function', 'function_expression', 'func_literal', 'lambda'}:
                    nested = True
                    break
                parent = parent.parent
            if nested:
                continue
            parts = pieces(node)
            if parts is None or sum(type(p) is int for p in parts) != 1:
                continue
            i = next(i for i, part in enumerate(parts) if type(part) is int)
            prefix, suffix = ''.join(parts[:i]), ''.join(parts[i + 1:])
            if not re.match(r'\s*SELECT\b', prefix, re.IGNORECASE) or not re.search(r'\bWHERE\s*\(*\s*$', prefix, re.IGNORECASE):
                continue
            templates[function['id']].append({'parameter_index': parts[i], 'prefix': prefix, 'suffix': suffix,
                                             'span': {'path': source.path, 'start_byte': node.start_byte, 'end_byte': node.end_byte}})
    return templates


def _fragment_contexts(donor, templates, frontend, max_depth=4):
    if not frontend:
        return []
    functions = {f['id']: f for f in frontend.get('functions', [])}
    calls = {_position(c): c for c in frontend.get('calls', [])}
    forwarding = defaultdict(list)
    for call in frontend.get('production_calls', []):
        forwarding[call['function_id']].append(call)
    queue = deque()
    for port in donor['aligned_ports']:
        if port.get('structural_path'):
            continue  # A whole-object formal does not prove a nested field use.
        call = calls.get(_position(port['call_span']))
        if call is None:
            continue
        for binding in call.get('argument_bindings', []):
            resolved = any(t['function_id'] == binding['function_id'] and t.get('resolved') for t in call.get('targets', []))
            if resolved and binding['slot'] == port['argument_slot'] and binding.get('binding_status') == 'direct_actual_formal':
                queue.append((binding['function_id'], binding['parameter_index'], [call['span']], 0))
    result, visited = [], set()
    while queue and len(visited) < 128:
        fid, parameter, trail, depth = queue.popleft()
        if (fid, parameter) in visited or depth >= max_depth:
            continue
        visited.add((fid, parameter))
        for template in templates.get(fid, []):
            if template['parameter_index'] == parameter:
                result.append(dict(template, binding_path=trail))
        function = functions.get(fid)
        if function is None:
            continue
        name = next((p['name'] for p in function['parameters'] if p['index'] == parameter), None)
        for call in forwarding[fid]:
            for binding in call.get('argument_bindings', []):
                arg = next((a for a in call['arguments'] if a['slot'] == binding['slot']), None)
                resolved = any(t['function_id'] == binding['function_id'] and t.get('resolved') for t in call.get('targets', []))
                if resolved and arg is not None and arg['kind'] == 'identifier' and arg['text'] == name:
                    queue.append((binding['function_id'], binding['parameter_index'], [*trail, call['span']], depth + 1))
    return result


def _add_predicate_fragments(raw, members, sources, frontend, budget, skipped):
    templates = _sql_templates(sources, frontend)
    full_reads = [(d, p) for d, p in members if p.kind == 'select']
    writes = defaultdict(list)
    for donor, program in members:
        if program.kind == 'update':
            writes[donor['test_id']].append(donor)
    deferred = []
    for donor, text in raw:
        keys = _alignment_keys(donor)
        contexts = []
        for origin, query in full_reads:
            alignment = keys.intersection(_alignment_keys(origin))
            if alignment:
                contexts.append((query.table, query.alias, {'kind': 'same_structural_slot_source_select', 'span': origin['span'],
                                                           'source_table_hint': list(query.table.key), 'table_identity': 'unknown',
                                                           'alignment': list(sorted(alignment, key=repr)),
                                                           'alignment_status': 'source_actual_slot' if any(k[0] == 'actual' for k in alignment)
                                                                                else 'formal_candidate_overlap_unresolved'}))
        for template in _fragment_contexts(donor, templates, frontend):
            program = parse_sql_program(template['prefix'] + text + template['suffix'], max_tokens=budget.max_tokens)
            if program is not None and program.kind == 'select':
                contexts.append((program.table, program.alias, dict(template, kind='resolved_source_string_template')))
        if not contexts and writes[donor['test_id']]:
            # The fragment is already a source input; an existing SQL write in
            # that test makes its field syntax a bounded hypothesis. Neither a
            # SELECT wrapper nor a table identity is constructed from this.
            contexts.append((None, None, {'kind': 'same_test_sql_write_fragment_syntax',
                                          'span': donor['span'], 'write_span': writes[donor['test_id']][0]['span'],
                                          'embedding_status': 'unknown', 'table_identity': 'unknown'}))
        if not contexts:
            deferred.append((donor, text))
        seen = set()
        for table, alias, evidence in contexts[:budget.max_read_sources]:
            table_key = table.key if table is not None else None
            if table_key in seen:
                continue
            tokens = _tokens(text, budget.max_tokens)
            if not tokens:
                continue
            try:
                predicates = _predicates(tokens, text, table, alias)
            except ValueError:
                if not _neutral_predicate(tokens):
                    continue
                predicates = []
            seen.add(table_key)
            inferred_table = table if evidence['kind'] == 'resolved_source_string_template' else None
            members.append((dict(donor, embedded_form='predicate_fragment', embedding_evidence=evidence),
                            SQLProgram(text, 'select', inferred_table, alias, tuple(predicates))))
            if len(members) >= budget.max_donors:
                skipped['donor_budget'] += 1
                return
    # A same-slot source predicate can supply coordinates to a neutral source
    # carrier. Both strings already exist; no parser command or wrapper is made.
    carriers = [(d, p) for d, p in members if d.get('embedded_form') == 'predicate_fragment']
    for donor, text in deferred:
        tokens = _tokens(text, budget.max_tokens)
        if not tokens:
            continue
        keys = _alignment_keys(donor)
        for recipient, query in carriers:
            if not keys.intersection(_alignment_keys(recipient)):
                continue
            try:
                predicates = _predicates(tokens, text, query.table, query.alias)
            except ValueError:
                continue
            if not predicates:
                continue
            evidence = {'kind': 'aligned_source_predicate_slot', 'span': recipient['span'],
                        'embedding_status': 'unknown', 'table_identity': 'unknown',
                        'recipient_embedding': recipient.get('embedding_evidence')}
            members.append((dict(donor, embedded_form='predicate_fragment', embedding_evidence=evidence),
                            SQLProgram(text, 'select', query.table, query.alias, tuple(predicates))))
            break
        if len(members) >= budget.max_donors:
            skipped['donor_budget'] += 1
            return


def generate_embedded_relations(corpus: dict, frontend: dict | None = None, *,
                                budget: EmbeddedRelationBudget = EmbeddedRelationBudget()) -> dict:
    """Return emitter-compatible SQL hypotheses with independent-oracle status.

    The recipient read and write belong to one test and explicitly named table.
    A read predicate can also come from an aligned source SELECT input, using
    a second exact edit. Lexical proximity and table syntax are not runtime
    database identity, row overlap, callback execution, or successful crossing.
    """
    skipped = Counter()
    sources = {path: Source(path, data['code'], data.get('language', corpus['language']))
               for path, data in corpus['sources'].items()
               if data.get('complete_file', True) and not data.get('parse_error')}
    tests = corpus['tests']
    ranked = sorted(tests, key=lambda key: (tests[key].get('retrieval_rank') or 10**9, _position(tests[key]), key))
    ranks = {key: i for i, key in enumerate(ranked)}
    seeds = set(ranked[:budget.top_k])
    capsules, calls = defaultdict(list), {}
    for capsule in corpus['capsules']:
        capsules[capsule['test_id']].append(capsule)
    if frontend:
        calls = {_position(call): call for call in frontend.get('calls', [])}
    members, raw_fragments = [], []
    donors = sorted(expanded_donors(corpus), key=lambda d: (ranks.get(d['test_id'], 10**9), _position(d), d['id']))
    for donor in donors:
        if donor['test_id'] not in tests or not capsules[donor['test_id']] or donor['span']['path'] not in sources:
            continue
        if donor.get('role') == 'diagnostic':
            continue
        if not donor.get('literal_known') or not isinstance(donor.get('literal_value'), str) or donor.get('free_identifiers'):
            continue
        value = _source_string(donor, sources[donor['span']['path']].language)
        if value is None:
            skipped['unsupported_host_literal'] += 1
            continue
        if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            skipped['unsupported_host_literal'] += 1
            continue
        if len(value.encode()) > budget.max_string_bytes:
            skipped['string_size_budget'] += 1
            continue
        ports = carrier_ports(sources[donor['span']['path']], donor, frontend)
        if not ports:
            continue
        ports = [dict(port, formal_slots=[b for b in calls.get(_position(port['call_span']), {}).get('argument_bindings', [])
                                         if b['slot'] == port['argument_slot'] and b.get('binding_status') == 'direct_actual_formal'])
                 for port in ports]
        program = parse_sql_program(value, max_tokens=budget.max_tokens)
        if program is None:
            if not donor.get('oracle_dependency') and not expected_only(donor):
                # Apply the fragment budget to possible predicate syntax, not
                # every unrelated source string that precedes it in a test.
                # This recognizes syntax only; embedding/table evidence still
                # has to be recovered by _add_predicate_fragments.
                tokens = _tokens(value, budget.max_tokens)
                if tokens and _neutral_predicate(tokens):
                    raw_fragments.append((dict(donor, aligned_ports=ports), value))
                else:
                    skipped['non_predicate_source_string'] += 1
            continue
        if program.kind != 'select' and (donor.get('role') == 'expected' or expected_only(donor) or donor.get('oracle_dependency')):
            continue
        members.append((dict(donor, aligned_ports=ports), program))
        if len(members) >= budget.max_donors:
            skipped['donor_budget'] += 1
            break
    _add_predicate_fragments(raw_fragments[:budget.max_donors], members, sources, frontend, budget, skipped)
    reads = defaultdict(list)
    writes = []
    for donor, program in members:
        if program.kind == 'select':
            reads[donor['test_id']].append((donor, program))
        else:
            writes.append((donor, program))
    pool = {}
    for target, update in writes:
        if target['test_id'] not in seeds:
            skipped['write_owner_outside_seed_budget'] += 1
            continue
        if not reads[target['test_id']]:
            skipped['no_same_test_read_or_fragment'] += 1
        for read, recipient_query, source_read, query in _read_pairs(target['test_id'], reads, budget):
            if query.table is not None and query.table.key != update.table.key:
                skipped['different_or_unresolved_table'] += 1
                continue
            read_edit = None
            if source_read['id'] != read['id']:
                language = sources[read['span']['path']].language
                read_after = format_source_string(query.text, language, read['text'])
                if read_after is None:
                    skipped['unsupported_host_literal'] += 1
                    continue
                read_edit = {'span': read['span'], 'before': read['text'], 'after': read_after}
            # Both source calls precede or occur inside an existing observation.
            call_ends = [min(port['call_span']['end_byte'] for port in donor['aligned_ports']) for donor in (read, target)]
            observations = [item for item in capsules[target['test_id']]
                            if item['span']['end_byte'] >= max(call_ends)]
            if not observations:
                skipped['no_later_source_observation'] += 1
                continue
            for predicate in query.predicates[:budget.max_predicates]:
                field = predicate.field.leaf
                assignment = next((a for a in update.assignments if a.field.key == field.key), None)
                # Avoid adding a possible duplicate when dialect-specific quote
                # folding prevents a proven field match.
                folded = lambda item: item.tokens[-1].text.strip('"`[]').casefold()
                if assignment is None and any(folded(a.field) == folded(field) for a in update.assignments):
                    skipped['unresolved_field_identity'] += 1
                    continue
                options = [(*_boundary(predicate, offset), 'predicate_boundary', offset, None, None)
                           for offset in budget.boundary_offsets]
                aligned = {structural_slot_key(port) for port in target['aligned_ports']}
                reused = 0
                for origin, source_update in writes:
                    if source_update.table.key != update.table.key or not aligned.intersection(structural_slot_key(p) for p in origin['aligned_ports']):
                        continue
                    for existing in source_update.assignments:
                        if existing.field.key != field.key or existing.numeric is None:
                            continue
                        if assignment is not None and assignment.numeric is not None and _truth(existing.numeric, predicate) == _truth(assignment.numeric, predicate):
                            continue
                        options.append((source_update.text[existing.value_start:existing.value_end], existing.numeric,
                                        'source_assignment', None, (origin, source_update), existing))
                        reused += 1
                        if reused >= budget.max_assignment_sources:
                            break
                    if reused >= budget.max_assignment_sources:
                        break
                for spelling, number, basis, offset, origin_pair, origin_assignment in options:
                    if assignment:
                        start, end = assignment.value_start, assignment.value_end
                        replacement = spelling
                    else:
                        start = end = update.assignments[-1].end
                        replacement = ', ' + field.tokens[0].text + ' = ' + spelling
                    after_sql = update.text[:start] + replacement + update.text[end:]
                    if after_sql == update.text:
                        continue
                    if len(after_sql.encode()) > budget.max_string_bytes:
                        skipped['output_string_size_budget'] += 1
                        continue
                    language = sources[target['span']['path']].language
                    after = format_source_string(after_sql, language, target['text'])
                    if after is None:
                        skipped['unsupported_host_literal'] += 1
                        continue
                    edit = {'span': target['span'], 'before': target['text'], 'after': after}
                    edits = [edit, *([read_edit] if read_edit else [])]
                    if any(not contained(item['span'], tests[target['test_id']]['span'])
                           or source_text(corpus, item['span']) != item['before'] for item in edits):
                        skipped['source_edit_mismatch'] += 1
                        continue
                    identifier = stable_id('embedded-sql-relation-v1', target['test_id'], edits)
                    if identifier in pool:
                        continue
                    origin = origin_pair[0] if origin_pair else None
                    facts = [_source_fact(source_read, query, predicate.start, predicate.end, 'read_predicate'),
                             _source_fact(target, update, 0, len(update.text), 'source_write')]
                    embedding = source_read.get('embedding_evidence')
                    embedding_spans = [embedding['span'], *embedding.get('binding_path', [])] if embedding else []
                    if embedding and embedding.get('write_span'):
                        embedding_spans.append(embedding['write_span'])
                    if read_edit:
                        facts.append(_source_fact(read, recipient_query, 0, len(recipient_query.text), 'recipient_read'))
                    if origin_pair:
                        facts.append(_source_fact(origin, origin_pair[1], origin_assignment.start, origin_assignment.end, 'assignment_value'))
                    source_ids = sorted({target['test_id'], source_read['test_id'], *([origin['test_id']] if origin else [])})
                    dependency_ids = sorted({oid for port in read['aligned_ports']
                                             for oid in calls.get(_position(port['call_span']), {}).get('observation_ids', [])
                                             if oid in {item['id'] for item in observations}})
                    pool[identifier] = {
                        'id': identifier, 'kind': 'embedded_sql_read_write', 'base_test_id': target['test_id'],
                        'focus_test_id': target['test_id'], 'source_test_ids': source_ids,
                        'language': language, 'edits': edits, 'imports': [],
                        'relation': {'domain': 'embedded_sql_predicate_write',
                                     'cell': {'read_field': list(field.key), 'write_relation': 'same_predicate_field',
                                              'assigned_predicate_truth': _truth(number, predicate)},
                                     'source_observation_ids': [item['id'] for item in observations],
                                     'read_source_basis': 'aligned_source_query_transfer' if read_edit else 'recipient_source_query',
                                     'read_transfer_alignment': list(sorted(_alignment_keys(read).intersection(_alignment_keys(source_read)), key=repr)) if read_edit else [],
                                     'read_transfer_alignment_status': ('source_actual_slot' if any(k[0] == 'actual' for k in
                                                                       _alignment_keys(read).intersection(_alignment_keys(source_read)))
                                                                       else 'formal_candidate_overlap_unresolved') if read_edit else 'same_source_input',
                                     'read_embedded_form': source_read.get('embedded_form', 'statement'),
                                     'read_embedding_evidence': source_read.get('embedding_evidence'),
                                     'read_input_slot': list(slot_key(read['aligned_ports'][0])),
                                     'read_structural_path': read['aligned_ports'][0].get('structural_path', []),
                                     'write_structural_path': target['aligned_ports'][0].get('structural_path', []),
                                     'read_dependency_observation_ids': dependency_ids,
                                     'observation_alignment': 'source_call_dependency' if dependency_ids else 'same_test_lexical_before_observation',
                                     'table': list(update.table.key),
                                     'table_identity': ('unknown_fragment_to_write' if query.table is None else
                                                        'source_embedding_context' if embedding else 'same_explicit_source_identifier'),
                                     'source_write_relation': 'same_predicate_field' if assignment else 'other_fields',
                                     'predicate': {'operator': predicate.operator, 'threshold': predicate.literal},
                                     'assigned_value': spelling, 'value_basis': basis, 'boundary_offset': offset,
                                     'source_assigned_predicate_truth': _truth(assignment.numeric, predicate) if assignment and assignment.numeric is not None else None,
                                     'embedded_edit': {'decoded_string_range': [start, end], 'before': update.text[start:end], 'after': replacement},
                                     'where_preserved': update.where_text,
                                     'status': 'statically_constructed_runtime_unconfirmed',
                                     'unknowns': ['database_receiver_identity', 'selected_row_overlap', 'initial_predicate_truth',
                                                  'full_where_truth', 'column_type_and_constraints', 'runtime_phase_and_effects']
                                                 + (['fragment_language_embedding', 'fragment_table_identity'] if query.table is None else [])},
                        'oracle': {'mode': 'retain_all', 'source_test_id': target['test_id'],
                                   'assertion_ids': [item['id'] for item in capsules[target['test_id']]],
                                   'applicability': 'requires_independent_admission', 'basis': None,
                                   'immutable_read_input_feeds_expected': bool(read.get('oracle_dependency'))},
                        'provenance': {'target_span': target['span'], 'source_spans': [fact['span'] for fact in facts] + embedding_spans,
                                       'source_donor_ids': [fact['donor_id'] for fact in facts], 'source_facts': facts,
                                       'input_carriers': {'read': read['aligned_ports'], 'write': target['aligned_ports']},
                                       'binding_precision': 'source_call_slots; database_and_rows_unproved'},
                        'selection': {'focus_order': ranks[target['test_id']], 'base_order': ranks[target['test_id']],
                                      'base_position': _position(tests[target['test_id']]),
                                      'edit_size': sum(max(len(item['before'].encode()), len(item['after'].encode())) for item in edits)}}
                    if len(pool) >= budget.max_pool:
                        break
                if len(pool) >= budget.max_pool:
                    break
            if len(pool) >= budget.max_pool:
                break
        if len(pool) >= budget.max_pool:
            skipped['pool_budget'] += 1
            break
    queues = defaultdict(deque)
    for candidate in pool.values():
        queues[candidate['base_test_id']].append(candidate)
    candidates = []
    while queues and len(candidates) < budget.max_candidates:
        for test_id in list(queues):
            candidates.append(queues[test_id].popleft())
            if not queues[test_id]:
                del queues[test_id]
            if len(candidates) >= budget.max_candidates:
                break
    return {'candidates': candidates, 'counts': {'sql_inputs': len(members), 'read_inputs': sum(map(len, reads.values())),
                                               'neutral_read_inputs': sum(not p.predicates for rows in reads.values() for _, p in rows),
                                               'write_inputs': len(writes), 'pool': len(pool), 'candidates': len(candidates),
                                               'skipped': dict(sorted(skipped.items()))},
            'budget': asdict(budget), 'status': 'static_hypotheses_not_checked_gaps',
            'limitations': ['single_explicit_table_select_update_only', 'numeric_comparison_leaf_boundaries',
                            'same_recipient_test_read_write_pairing_with_bounded_aligned_source_queries',
                            'no_schema_type_or_runtime_database_identity_proof',
                            'retained_oracle_requires_independent_admission']}
