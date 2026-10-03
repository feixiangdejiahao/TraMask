"""Refine one buffered HTTP body into byte-identical synchronous chunks.

HTTP content is a byte sequence. Chunk boundaries are transport choices, while
raw-chunk observers and stream lifecycle observers are representation-sensitive.
This adapter therefore retains only a single issue-named semantic iterator use
of an unaliased Response. An existing streaming test supplies a source control.
The adapter is intentionally limited to HTTPX/Python; it is not a general law
for arbitrary iterables or callbacks.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import hashlib
import json

from anchor_retrieval.syntax import Source
from relation_search.edited_contract_call_priority import issue_names

VERSION = 'http-byte-stream-refinement.v1'
CHUNK_SIZES = (1, 2, 3, 7)
MAX_BODY = 16384
POLICY = dict(version=VERSION, language='python', adapter='unshadowed httpx.Response(content=...)',
    authority='HTTP content is a byte sequence; the issue names a semantic iterator and an existing source test exercises it on a byte stream',
    transformation='replace only the content expression with a synchronous generator of adjacent byte slices; preserve concatenation exactly',
    eligibility='one unaliased response, exactly one issue-named iter_* call, no other receiver reads, closed finite bytes domain',
    exclusions=['raw/chunk/text/line iterators', 'repeated consumption', 'lifecycle/header/body-property assertions',
                'dynamic bodies', 'asynchronous tests', 'nonrepository tests', 'shadowed Python builtins'],
    source_controls='original buffered test plus an existing streaming test of the same consumer',
    ordering='chunk size then source retrieval rank, source path and byte position', chunk_sizes=CHUNK_SIZES,
    forbidden_inputs=['known witness IDs', 'old candidates', 'runtime outcomes', 'audit labels', 'reference code', 'hidden tests'],
    limitations=['HTTPX adapter only', 'source tests and public contracts can be incomplete',
                 'native controls and independent full-test review are still required'])
AUTHORITIES = ['https://www.rfc-editor.org/rfc/rfc9110.html#section-6.4',
               'https://www.python-httpx.org/api/#response']
CHUNK_OBSERVERS = {'iter_raw', 'iter_bytes', 'iter_text', 'iter_lines'}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _owned(node):
    yield node
    for part in ast.iter_child_nodes(node):
        if isinstance(part, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            yield part
            continue
        yield from _owned(part)


def _chain(node):
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        before = _chain(node.value)
        return before + [node.attr] if before else None
    return None


def _canonical(node, imports):
    parts = _chain(node)
    if not parts or parts[0] not in imports:
        return None
    module, name = imports[parts[0]]
    return '.'.join([module] + ([name] if name else []) + parts[1:])


def _stores(nodes):
    return {node.id for node in nodes if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}


def _binders(nodes):
    result = set()
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            result.add(node.id)
        elif isinstance(node, ast.arg):
            result.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            result.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            result.update(alias.asname or alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            parts = _chain(node)
            if parts:
                result.add(parts[0])
    return result


def _literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


class _File:
    def __init__(self, path, row):
        self.path, self.code = path, row['code']
        self.data = self.code.encode()
        self.tree = ast.parse(self.code)
        self.imports = Source(path, self.code, 'python').imports
        self.starts = [0]
        for line in self.data.splitlines(keepends=True):
            self.starts.append(self.starts[-1] + len(line))
        self.parents = {id(child): node for node in ast.walk(self.tree) for child in ast.iter_child_nodes(node)}
        self.module_stores = _binders(node for node in _owned(self.tree)
                                      if not isinstance(node, (ast.Import, ast.ImportFrom)))

    def span(self, node):
        return dict(path=self.path, start_byte=self.starts[node.lineno-1] + node.col_offset,
                    end_byte=self.starts[node.end_lineno-1] + node.end_col_offset)

    def text(self, node):
        position = self.span(node)
        return self.data[position['start_byte']:position['end_byte']].decode()

    def function(self, test):
        extent = test.get('definition_span')
        if extent is None:
            return None
        found = [node for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)
                 and self.span(node)['start_byte'] == extent['start_byte']]
        return found[0] if len(found) == 1 else None


def _bytes_domain(node, function, file, seen=None):
    seen = set() if seen is None else set(seen)
    value = _literal(node)
    if isinstance(value, bytes):
        return [value] if len(value) <= MAX_BODY else None
    if not isinstance(node, ast.Name) or node.id in seen:
        return None
    seen.add(node.id)
    writes = [part for part in _owned(function) if isinstance(part, (ast.Assign, ast.AnnAssign))
              and node.id in _stores(_owned(part))]
    if writes:
        if len(writes) != 1 or writes[0] not in function.body or writes[0].lineno >= node.lineno:
            return None
        statement = writes[0]
        if isinstance(statement, ast.Assign) and (len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name)):
            return None
        return _bytes_domain(statement.value, function, file, seen)
    domains = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or _canonical(decorator.func, file.imports) != 'pytest.mark.parametrize':
            continue
        if len(decorator.args) != 2 or any(kw.arg == 'indirect' and _literal(kw.value) is not False
                                           for kw in decorator.keywords):
            continue
        names = _literal(decorator.args[0])
        if isinstance(names, str):
            names = [name.strip() for name in names.split(',')]
        if not isinstance(names, (tuple, list)) or node.id not in names or len(set(names)) != len(names):
            continue
        rows = _literal(decorator.args[1])
        if not isinstance(rows, (tuple, list)) or not rows:
            return None
        values = []
        for row in rows:
            if len(names) == 1:
                value = row
            elif isinstance(row, (tuple, list)) and len(row) == len(names):
                value = row[names.index(node.id)]
            else:
                return None
            if not isinstance(value, bytes) or len(value) > MAX_BODY:
                return None
            values.append(value)
        domains.append(values)
    return domains[0] if len(domains) == 1 else None


def _stream_body(node, function):
    if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.args or node.keywords:
        return False
    definitions = [part for part in function.body if isinstance(part, ast.FunctionDef) and part.name == node.func.id]
    if len(definitions) != 1:
        return False
    definition = definitions[0]
    if definition.args.args or definition.args.kwonlyargs or definition.args.vararg or definition.args.kwarg:
        return False
    yields = [part for part in _owned(definition) if isinstance(part, ast.Yield)]
    return bool(yields) and all(isinstance(_literal(part.value), bytes) for part in yields)


def _context(file, function, named, *, strict=True):
    nodes = list(_owned(function))
    parameters = {arg.arg for arg in function.args.posonlyargs + function.args.args + function.args.kwonlyargs}
    rebound = _binders(nodes) | parameters | file.module_stores
    if {'range', 'len'} & (rebound | set(file.imports)):
        return None
    found = []
    for statement in function.body:
        if not isinstance(statement, ast.Assign) or len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        call = statement.value
        if not isinstance(call, ast.Call) or _canonical(call.func, file.imports) != 'httpx.Response':
            continue
        root = _chain(call.func)[0]
        if root in rebound:
            continue
        if any(keyword.arg is None for keyword in call.keywords):
            continue
        contents = [keyword.value for keyword in call.keywords if keyword.arg == 'content']
        if len(contents) != 1:
            continue
        receiver = statement.targets[0].id
        stores = [part for part in nodes if isinstance(part, ast.Name) and part.id == receiver and isinstance(part.ctx, ast.Store)]
        if len(stores) != 1:
            continue
        uses = [part for part in nodes if isinstance(part, ast.Name) and part.id == receiver and isinstance(part.ctx, ast.Load)]
        consumers = []
        for use in uses:
            member = file.parents[id(use)]
            parent = file.parents.get(id(member))
            if (not isinstance(member, ast.Attribute) or not isinstance(parent, ast.Call) or parent.func is not member
                    or not member.attr.startswith('iter_') or member.attr in CHUNK_OBSERVERS
                    or not ({member.attr, 'Response.' + member.attr} & named)):
                if strict:
                    break
                continue
            consumers.append((member.attr, parent))
        else:
            if len(consumers) == 1 or not strict and consumers and len({row[0] for row in consumers}) == 1:
                found.append(dict(receiver=receiver, content=contents[0], constructor=call,
                                  method=consumers[0][0], consumer=consumers[0][1]))
    return found[0] if len(found) == 1 else None


def generate(corpus, frontend, issue, *, limit=32):
    if corpus['language'] != 'python':
        return dict(version=VERSION, status='language_unsupported', candidates=[], total_candidates=0, skipped=[])
    named = set(issue_names(issue))
    files, eligible, donors, skipped = {}, [], defaultdict(list), []
    for identifier, test in sorted(corpus['tests'].items()):
        path = test['span']['path']
        row = corpus['sources'][path]
        if row.get('origin') != 'repository':
            continue
        if path not in files:
            if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
                raise ValueError('frontend_source_mismatch:' + path)
            try:
                files[path] = _File(path, row)
            except SyntaxError:
                files[path] = None
        file = files[path]
        function = file.function(test) if file else None
        if function is None:
            continue
        context = _context(file, function, named)
        strict = context is not None
        if context is None:
            context = _context(file, function, named, strict=False)
        if context is None:
            continue
        domain = _bytes_domain(context['content'], function, file)
        record = dict(base=identifier, test=test, file=file, function=function, context=context, domain=domain)
        if domain is not None and strict:
            eligible.append(record)
        elif _stream_body(context['content'], function):
            donors[context['method']].append(record)
    order = lambda row: (row['test'].get('retrieval_rank', 100000), row['file'].path,
                         row['test']['span']['start_byte'])
    for method in donors:
        donors[method].sort(key=order)
    proposals = []
    for record in sorted(eligible, key=order):
        context, file = record['context'], record['file']
        if context['method'] not in donors:
            skipped.append(dict(base_test_id=record['base'], reason='no_source_streaming_control'))
            continue
        donor = donors[context['method']][0]
        before = file.text(context['content'])
        position = file.span(context['content'])
        for size_rank, size in enumerate(CHUNK_SIZES):
            after = (f'(lambda _cc_payload: (_cc_payload[_cc_offset:_cc_offset+{size}] '
                     f'for _cc_offset in range(0,len(_cc_payload),{size})))({before})')
            edit = dict(span=position, before=before, after=after, role='input')
            identity = digest([VERSION, record['base'], hashlib.sha256(file.data).hexdigest(), edit])[:24]
            proposals.append(dict(id='streamrefine_' + identity, base_test_id=record['base'],
                source_test_ids=[record['base'], donor['base']], imports=[], edits=[edit],
                kind='http_byte_stream_refinement', operator='fixed_size_byte_chunks', generator=VERSION,
                source_evidence=dict(authority=AUTHORITIES, consumer=context['method'],
                    constructor_span=file.span(context['constructor']), consumer_span=file.span(context['consumer']),
                    source_streaming_control=donor['base'], buffered_domain_size=len(record['domain']),
                    body_lengths=[len(value) for value in record['domain']],
                    payload_sha256=[hashlib.sha256(value).hexdigest() for value in record['domain']],
                    chunk_size=size, exact_byte_concatenation=True),
                oracle_status='http_content_representation_relation_pending_native_control',
                order=[size_rank, *order(record)]))
    ranking = sorted(proposals, key=lambda row: (row['order'], row['id']))
    return dict(version=VERSION, status='source_candidates', candidates=ranking[:limit],
                total_candidates=len(ranking), eligible_buffered_tests=len(eligible),
                streaming_control_tests=sum(map(len, donors.values())), selected=min(limit, len(ranking)), skipped=skipped)
