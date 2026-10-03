"""Construct default-omission tests from scoped documentation tables.

Documentation supplies the default. Implementation bodies never supply the
expected result. A matching table and a resolved call establish bounded source
evidence, not a formal proof that documentation or every retained assertion is
correct. Native source controls and independent alert review remain necessary.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import re

from anchor_retrieval.syntax import CALLS, Source, call_parts, child, literal, walk
from relational_gap.frontend import TRUSTED_RESOLUTIONS

VERSION = 'scoped-documented-default-omission.v1'
POLICY = dict(version=VERSION, language='typescript',
    authority='literal Default cells in Option/Type/Default tables beneath an exact class heading and method heading',
    binding='one uniquely resolved frontend method, matching the documentation owner and method',
    construction='one scalar field equal to its documented default is removed from an inline literal options record',
    optional_argument='also omit the entire sole argument when the declared argument default is an empty object',
    unchanged='complete source test, assertions, all other inputs, receiver and callee',
    ordering='source retrieval rank, test source path, call byte offset, field name, field then argument omission',
    unknown='ambiguous declarations, conflicting documents, dynamic records and nonliteral defaults are not eligible',
    forbidden_inputs=['evaluation labels', 'reference implementation', 'hidden tests', 'runtime outcomes', 'model answers'],
    limitation='Documentation can be stale or incomplete. These candidates require native controls and independent alert review.')
IDENTIFIER = re.compile(r'[A-Za-z_$][\w$]*')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                    separators=(',', ':')).encode()).hexdigest()


def _cell_code(text):
    match = re.fullmatch(r'`([^`]+)`', text.strip())
    return match.group(1).strip() if match else None


def _scalar(text, *, enum_tokens=()):
    if text in {'true', 'false', 'null'}:
        return dict(kind={'true': 'boolean', 'false': 'boolean', 'null': 'null'}[text],
                    value={'true': True, 'false': False, 'null': None}[text])
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?', text):
        value = json.loads(text)
        if value == 0 and text.startswith('-'):
            raise ValueError('negative_zero')
        return dict(kind='number', value=value)
    if text.startswith(('"', "'")) and text[-1:] == text[:1]:
        value = literal(text)
        if isinstance(value, str):
            return dict(kind='string', value=value)
    if IDENTIFIER.fullmatch(text) and text in enum_tokens:
        return dict(kind='string', value=text)
    raise ValueError('nonliteral_default')


def _cells(line):
    # Pipe characters inside code spans belong to a cell, not to the table.
    cells, current, quoted = [], [], False
    for character in line.strip().strip('|'):
        if character == '`':
            quoted = not quoted
        if character == '|' and not quoted:
            cells.append(''.join(current).strip())
            current = []
        else:
            current.append(character)
    cells.append(''.join(current).strip())
    return cells


def extract(documents):
    """Keep exact table receipts and reject disagreement across documents."""
    found = defaultdict(list)
    rejected = []
    for document in sorted(documents, key=lambda row: row['path']):
        code = document['text']
        sha = hashlib.sha256(code.encode()).hexdigest()
        owner = method = None
        method_level = None
        headings = []
        in_fence = False
        lines = code.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith(('```', '~~~')):
                in_fence = not in_fence
            if in_fence:
                i += 1
                continue
            heading = re.match(r'^(#{1,6})\s+(.+?)\s*#*$', line)
            if heading:
                level, text = len(heading.group(1)), heading.group(2).strip()
                headings = [row for row in headings if row[0] < level] + [(level, text)]
                if level == 1:
                    name = _cell_code(text) or text
                    owner = name if IDENTIFIER.fullmatch(name) else None
                if method_level is not None and level <= method_level:
                    method = method_level = None
                match = re.fullmatch(r'([A-Za-z_$][\w$]*)\([^)]*\)', _cell_code(text) or text)
                if level > 1 and match:
                    method, method_level = match.group(1), level
            if owner and method and line.strip().startswith('|') and i + 1 < len(lines):
                header = [cell.lower() for cell in _cells(line)]
                separator = _cells(lines[i + 1])
                if (all(key in header for key in ('option', 'type', 'default'))
                        and len(separator) == len(header)
                        and all(re.fullmatch(r':?-{3,}:?', value) for value in separator)):
                    start = i
                    i += 2
                    while i < len(lines) and lines[i].strip().startswith('|'):
                        cells = _cells(lines[i])
                        if len(cells) == len(header):
                            row = dict(zip(header, cells))
                            field = _cell_code(row['option'])
                            default = _cell_code(row['default'])
                            if field and IDENTIFIER.fullmatch(field) and field != '__proto__' and default is not None:
                                try:
                                    value = _scalar(default, enum_tokens=re.findall(r'`([^`]+)`', row['type']))
                                except ValueError:
                                    rejected.append(dict(path=document['path'], line=i + 1,
                                                         reason='nonliteral_or_conditional_default'))
                                else:
                                    found[owner, method, field].append(dict(owner=owner, method=method,
                                        field=field, scalar=value, path=document['path'], sha256=sha,
                                        table_header_line=start + 1, row_line=i + 1, row=lines[i],
                                        headings=[text for _, text in headings]))
                        i += 1
                    continue
            i += 1
    facts, conflicts = [], []
    for key, rows in sorted(found.items()):
        if len({digest(row['scalar']) for row in rows}) != 1:
            conflicts.append(dict(owner=key[0], method=key[1], field=key[2],
                                  reason='conflicting_documented_defaults', sources=rows))
        else:
            facts.append(dict(owner=key[0], method=key[1], field=key[2],
                              scalar=rows[0]['scalar'], sources=rows))
    return dict(version=VERSION, facts=facts, conflicts=conflicts, rejected=rejected)


def _extent(node, path):
    return dict(path=path, start_byte=node.start_byte, end_byte=node.end_byte)


def _exact(source, extent):
    if extent['path'] != source.path:
        return None
    node = source.root.named_descendant_for_byte_range(extent['start_byte'], max(extent['start_byte'], extent['end_byte'] - 1))
    while node is not None:
        if node.start_byte == extent['start_byte'] and node.end_byte == extent['end_byte']:
            return node
        node = node.parent
    return None


def _empty_object_default(source, parameter):
    default = parameter.get('default')
    if default is None:
        return False
    node = _exact(source, default['span'])
    while node is not None and node.type in {'as_expression', 'parenthesized_expression'}:
        node = node.named_children[0] if node.named_children else None
    return node is not None and node.type == 'object' and not node.named_children


def _record(source, node):
    if node.type != 'object':
        return None
    fields = []
    for pair in node.named_children:
        if pair.type == 'comment':
            continue
        if pair.type != 'pair':
            return None
        key, value = child(pair, 'key'), child(pair, 'value')
        if key is None or value is None or key.type not in {'property_identifier', 'string'}:
            return None
        name = source.text(key) if key.type == 'property_identifier' else literal(source.text(key))
        if not isinstance(name, str) or name == '__proto__':
            return None
        try:
            scalar = _scalar(source.text(value))
        except ValueError:
            return None
        fields.append(dict(name=name, scalar=scalar, node=pair))
    if len({row['name'] for row in fields}) != len(fields):
        return None
    return fields


def generate(corpus, frontend, document_evidence, *, limit=16):
    """Generate complete test clones. Never import old candidates or labels."""
    if corpus['language'] != 'typescript':
        return dict(version=VERSION, status='language_unsupported', candidates=[], skipped=[])
    functions = {row['id']: row for row in frontend.get('functions', [])}
    declarations = defaultdict(list)
    for row in functions.values():
        if row.get('production') and row.get('owner'):
            declarations[row['owner'], row['name']].append(row)
    facts = defaultdict(list)
    for row in document_evidence['facts']:
        facts[row['owner'], row['method']].append(row)
    sources = {}
    def source(path):
        if path not in sources:
            code = corpus['sources'][path]['code']
            if frontend.get('sources', {}).get(path, {}).get('code') != code:
                raise ValueError('frontend_source_mismatch:' + path)
            sources[path] = Source(path, code, 'typescript')
        return sources[path]
    proposals, skipped = [], []
    for call in frontend.get('calls', []):
        base = call.get('test_id')
        if base not in corpus['tests']:
            continue
        resolved = [row for row in call.get('targets', []) if row.get('resolved')
                    and row.get('reason') in TRUSTED_RESOLUTIONS]
        if len({row['function_id'] for row in resolved}) != 1:
            continue
        function = functions.get(resolved[0]['function_id'])
        if function is None:
            continue
        key = function.get('owner'), function['name']
        if key not in facts:
            continue
        if len(declarations[key]) != 1 or len(function.get('parameters', [])) != 1:
            skipped.append(dict(call_id=call['id'], reason='ambiguous_method_or_argument_scope'))
            continue
        parameter = function['parameters'][0]
        if parameter['index'] != 0 or parameter.get('variadic'):
            continue
        src = source(call['span']['path'])
        node = _exact(src, call['span'])
        if node is None or node.type not in CALLS or src.root.has_error:
            skipped.append(dict(call_id=call['id'], reason='source_call_unresolved'))
            continue
        callee, arguments = call_parts(node)
        arguments = [arg for arg in arguments if arg.type != 'comment']
        if src.text(callee) != call['callee'] or len(arguments) != 1:
            continue
        # Metadata must link this exact argument to the documented method.
        if not any(row.get('function_id') == function['id'] and row.get('slot') == 0
                   and row.get('parameter_index') == 0 and row.get('binding_status') == 'direct_actual_formal'
                   and row.get('resolution') in TRUSTED_RESOLUTIONS for row in call.get('argument_bindings', [])):
            continue
        fields = _record(src, arguments[0])
        if fields is None:
            skipped.append(dict(call_id=call['id'], reason='options_record_is_not_closed_scalar_data'))
            continue
        declared = source(function['span']['path'])
        optional = _empty_object_default(declared, parameter)
        test = corpus['tests'][base]
        for fact in facts[key]:
            field = next((row for row in fields if row['name'] == fact['field']), None)
            if field is None or field['scalar'] != fact['scalar']:
                continue
            remaining = [row for row in fields if row is not field]
            replacement = '{' + ', '.join(src.text(row['node']) for row in remaining) + '}'
            forms = [('field', arguments[0], replacement)]
            if not remaining and optional:
                forms.append(('argument', arguments[0], ''))
            for form, edited, after in forms:
                edit = dict(span=_extent(edited, src.path), before=src.text(edited), after=after, role='input')
                identity = digest([VERSION, hashlib.sha256(src.data).hexdigest(), base, edit, fact])[:24]
                header_end = function.get('body_span', function['span'])['start_byte']
                proposals.append(dict(id='docdefault_' + identity, base_test_id=base,
                    source_test_ids=[base], imports=[], edits=[edit],
                    kind='documented_default_omission', operator='documented_default_' + form,
                    generator=VERSION, oracle_status='documentation_supported_equivalence_pending_native_control',
                    source_evidence=dict(basis='scoped_documentation_default_and_resolved_source_call',
                        call_span=call['span'], declaration_span=function['span'],
                        documentation_sources=fact['sources'], default_scalar=fact['scalar']),
                    documented_default=dict(fact=fact, call_id=call['id'], function_id=function['id'],
                        declaration_header=declared.data[function['span']['start_byte']:header_end].decode(),
                        binding_basis=resolved[0]['reason'], optional_empty_record_argument=optional,
                        implementation_bodies_used_as_oracle=False),
                    order=[test.get('retrieval_rank', 100000), src.path, node.start_byte,
                           fact['field'], 0 if form == 'field' else 1]))
    unique = {digest([row['base_test_id'], row['edits']]): row for row in proposals}
    ranking = sorted(unique.values(), key=lambda row: (row['order'], row['id']))
    return dict(version=VERSION, status='source_candidates', candidates=ranking[:limit],
                total_candidates=len(ranking), selected=len(ranking[:limit]), skipped=skipped)
