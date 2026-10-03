"""Lift a source close-state observer onto a byte-preserving failure path.

The public issue must require stream consumption and response closure. The
source error test and successful streaming control must share all constructor
arguments except the body representation. This HTTPX adapter adds the source
close-state assertion after the original expected decoding error.
"""
from __future__ import annotations

import ast
from collections import defaultdict
import copy
import hashlib
import re

from relation_search import byte_stream_refinement as stream
from relation_search.edited_contract_call_priority import issue_names

VERSION = 'http-error-path-finalization.v1'
POLICY = dict(version=VERSION, adapter='Python HTTPX response semantic iterator',
    premise='Issue explicitly requires streamed iteration to consume and close the response; do not infer it from an API name.',
    source_pair='Existing buffered DecodingError test plus successful streaming test of the same consumer and identical closed constructor configuration.',
    relation='Preserve body bytes and existing exception oracle; activate streaming representation and append the source close-state observer.',
    donor='Source close-state assertion follows proven iterator exhaustion, without explicit close, aliasing or other receiver operations.',
    exclude=['invalid or unmatched constructor headers', 'dynamic constructor options', 'asynchronous tests',
             'raw/chunk observers', 'shadowed builtins/imports', 'multiple receiver bindings', 'unknown completion paths'],
    ordering='source retrieval rank, path and test position', max_candidates_per_trial=16,
    forbidden_inputs=['known witness IDs', 'old candidates', 'runtime outcomes during generation', 'audit labels', 'reference code'],
    limitations=['HTTPX adapter only; one issue-named synchronous semantic iterator',
                 'The issue must state a total close obligation; qualified success-only obligations are rejected.',
                 'Source controls do not replace independent complete-test audit.'])


def contract(issue):
    facts = []
    for match in re.finditer(r'[^.!?\n]+[.!?]?', issue):
        sentence = match.group().strip()
        text = sentence.lower().replace('`', '')
        if (re.match(r'^(?:for\s+streaming\s+responses|if\s+(?:the\s+)?response\s+body\s+is\s+streaming)\b', text)
                and re.search(r'\b(?:iteration|iterating)\b', text)
                and re.search(r'\bconsum(?:e|es)\b.*\bstream\b', text)
                and re.search(r'\bclos(?:e|es)\s+(?:the\s+)?response[.!]?$', text)
                and (re.search(r'\bmust\s+consume\b', text) or re.search(r'\biteration\s+consumes\b', text))
                and not re.search(r'\b(?:not|never|except|unless|only|may|might|can|success|successful|successfully)\b', text)):
            facts.append(dict(text=sentence, start=match.start(), end=match.end(),
                              issue_sha256=hashlib.sha256(issue.encode()).hexdigest()))
    return facts


def _literal(node):
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return False, None


def _configuration(call):
    values = []
    for argument in call.args:
        known, value = _literal(argument)
        if not known:
            return None
        values.append(value)
    options = []
    for keyword in sorted(call.keywords, key=lambda part: part.arg or ''):
        if keyword.arg is None:
            return None
        if keyword.arg in {'content', 'stream'}:
            continue
        known, value = _literal(keyword.value)
        if not known:
            return None
        options.append((keyword.arg, value))
    return repr((values, options))


def _context(file, function, named, *, strict):
    # Reuse the original ownership checks. For an explicit stream constructor,
    # temporarily adapt just the AST keyword name, then restore it immediately.
    explicit = [node for node in ast.walk(function) if isinstance(node, ast.keyword) and node.arg == 'stream']
    for keyword in explicit:
        keyword.arg = 'content'
    try:
        context = stream._context(file, function, named, strict=strict)
    finally:
        for keyword in explicit:
            keyword.arg = 'stream'
    if context is None:
        return None
    if context['consumer'].args or context['consumer'].keywords:
        return None
    call = context['constructor']
    bodies = [kw for kw in call.keywords if kw.arg in {'content', 'stream'}]
    if len(bodies) != 1:
        return None
    context['body_keyword'] = bodies[0].arg
    context['configuration'] = _configuration(call)
    if context['configuration'] is None:
        return None
    rebound = stream._binders(ast.walk(function)) | file.module_stores | set(file.imports)
    if {'list', 'next', 'StopIteration'} & rebound:
        return None
    return context


def _raises(file, statement, exception):
    if not isinstance(statement, ast.With) or len(statement.items) != 1 or statement.items[0].optional_vars is not None:
        return False
    call = statement.items[0].context_expr
    if (not isinstance(call, ast.Call) or stream._canonical(call.func, file.imports) != 'pytest.raises'
            or len(call.args) != 1):
        return False
    owner = file.parents.get(id(statement))
    while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
        owner = file.parents.get(id(owner))
    root = stream._chain(call.func)[0]
    if owner is None or root in stream._binders(ast.walk(owner)) | file.module_stores:
        return False
    exc = call.args[0]
    return (stream._canonical(exc, file.imports) == exception if '.' in exception else
            isinstance(exc, ast.Name) and exc.id == exception)


def _expected_error(file, function, context):
    consumer = context['consumer']
    parent = file.parents[id(consumer)]
    if (not isinstance(parent, ast.Call) or not isinstance(parent.func, ast.Name) or parent.func.id != 'list'
            or parent.args != [consumer] or parent.keywords):
        return None
    statement = file.parents.get(id(parent))
    enclosing = file.parents.get(id(statement))
    if (not isinstance(statement, ast.Expr) or enclosing not in function.body
            or not _raises(file, enclosing, 'httpx.DecodingError') or enclosing.body != [statement]):
        return None
    root = stream._chain(enclosing.items[0].context_expr.func)[0]
    if root in stream._binders(ast.walk(function)) | file.module_stores:
        return None
    return enclosing


def _streamed(file, function, context):
    if context['body_keyword'] == 'content':
        return stream._stream_body(context['content'], function)
    value = context['content']
    if not isinstance(value, ast.Call) or not isinstance(value.func, ast.Name):
        return False
    classes = [node for node in file.tree.body if isinstance(node, ast.ClassDef) and node.name == value.func.id]
    return (len(classes) == 1 and any(stream._canonical(base, file.imports) == 'httpx.SyncByteStream'
                                     for base in classes[0].bases)
            and value.func.id not in stream._binders(ast.walk(function)))


def _completed_before(file, function, context, observer):
    consumer = context['consumer']
    parent = file.parents[id(consumer)]
    if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Name) and parent.func.id == 'list'
            and parent.args == [consumer] and not parent.keywords):
        top = parent
        while id(top) in file.parents and file.parents[id(top)] is not function:
            top = file.parents[id(top)]
            if not isinstance(top, (ast.Compare, ast.Assert, ast.Assign, ast.Expr)):
                return False
        return top in function.body and top.end_lineno < observer.lineno
    if not isinstance(parent, ast.Assign) or parent not in function.body or len(parent.targets) != 1:
        return False
    target = parent.targets[0]
    if not isinstance(target, ast.Name):
        return False
    stores = [node for node in ast.walk(function) if isinstance(node, ast.Name) and node.id == target.id
              and isinstance(node.ctx, (ast.Store, ast.Del))]
    if stores != [target]:
        return False
    for statement in function.body:
        if not parent.end_lineno < statement.lineno < observer.lineno or not _raises(file, statement, 'StopIteration'):
            continue
        if len(statement.body) != 1 or not isinstance(statement.body[0], ast.Expr):
            continue
        call = statement.body[0].value
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'next'
                and len(call.args) == 1 and isinstance(call.args[0], ast.Name)
                and call.args[0].id == target.id and not call.keywords):
            return True
    return False


def _close_observer(file, function, context):
    receiver = context['receiver']
    for statement in function.body:
        if not isinstance(statement, ast.Assert):
            continue
        value = statement.test
        if isinstance(value, ast.Compare) and len(value.ops) == 1 and isinstance(value.ops[0], (ast.Is, ast.Eq)):
            if (len(value.comparators) != 1 or not isinstance(value.comparators[0], ast.Constant)
                    or value.comparators[0].value is not True):
                continue
            value = value.left
        if (not isinstance(value, ast.Attribute) or not isinstance(value.value, ast.Name)
                or value.value.id != receiver or value.attr != 'is_closed'):
            continue
        if statement.msg is not None and not _literal(statement.msg)[0]:
            continue
        allowed = True
        for node in ast.walk(function):
            if (isinstance(node, ast.Name) and node.id == receiver and isinstance(node.ctx, ast.Load)
                    and node.lineno < statement.lineno):
                member = file.parents[id(node)]
                if not isinstance(member, ast.Attribute) or member.attr not in {
                        context['method'], 'is_closed', 'is_stream_consumed'}:
                    allowed = False
                    break
        if allowed and _completed_before(file, function, context, statement):
            return statement
    return None


def generate(corpus, frontend, issue, *, limit=16):
    facts = contract(issue)
    empty = dict(version=VERSION, candidates=[], total_candidates=0, skipped=[], contract=facts)
    if corpus['language'] != 'python':
        return dict(empty, status='language_unsupported')
    names = set(issue_names(issue))
    methods = {name.split('.')[-1] for name in names if name.split('.')[-1].startswith('iter_')
               and name.split('.')[-1] not in stream.CHUNK_OBSERVERS}
    if not facts or len(methods) != 1:
        return dict(empty, status='no_unambiguous_total_close_contract')
    files, errors, donors, skipped = {}, [], defaultdict(list), []
    for base, test in sorted(corpus['tests'].items()):
        path = test['span']['path']
        row = corpus['sources'][path]
        if row.get('origin') != 'repository':
            continue
        if path not in files:
            if frontend.get('sources', {}).get(path, {}).get('code') != row['code']:
                raise ValueError('frontend_source_mismatch:'+path)
            try:
                files[path] = stream._File(path, row)
            except SyntaxError:
                files[path] = None
        file = files[path]
        function = file.function(test) if file else None
        if function is None or file.parents.get(id(function)) is not file.tree:
            continue
        context = _context(file, function, names, strict=True)
        if context is not None and context['body_keyword'] == 'content':
            domain = stream._bytes_domain(context['content'], function, file)
            error = _expected_error(file, function, context)
            if domain is not None and error is not None:
                errors.append(dict(base=base, test=test, file=file, function=function,
                                   context=context, error=error, domain=domain))
        context = _context(file, function, names, strict=False)
        if context is not None and _streamed(file, function, context):
            observer = _close_observer(file, function, context)
            if observer is not None:
                donors[context['method'], context['configuration']].append(dict(
                    base=base, test=test, file=file, function=function, context=context, observer=observer))
    order = lambda row: (row['test'].get('retrieval_rank') or 100000, row['file'].path,
                         row['test']['span']['start_byte'])
    for rows in donors.values():
        rows.sort(key=order)
    candidates = []
    for record in sorted(errors, key=order):
        file, context = record['file'], record['context']
        matches = donors.get((context['method'], context['configuration']), [])
        if not matches:
            skipped.append(dict(base_test_id=record['base'], reason='no_successful_close_control_with_same_configuration'))
            continue
        donor = matches[0]
        observer = copy.deepcopy(donor['observer'])
        for node in ast.walk(observer):
            if isinstance(node, ast.Name) and node.id == donor['context']['receiver']:
                node.id = context['receiver']
        body = file.text(context['content'])
        error_text = file.text(record['error'])
        edits = [dict(span=file.span(context['content']), before=body,
                      after='(_cc_chunk for _cc_chunk in ('+body+',))', role='input'),
                 dict(span=file.span(record['error']), before=error_text,
                      after=error_text+'\n'+' '*record['error'].col_offset+ast.unparse(observer), role='observer')]
        identity = stream.digest([VERSION, record['base'], edits, donor['base']])[:24]
        candidates.append(dict(id='finalize_'+identity, base_test_id=record['base'],
            source_test_ids=[record['base'], donor['base']], edits=edits, imports=[], generator=VERSION,
            kind='declared_stream_finalization', operator='error_path_close_observer',
            source_evidence=dict(contract=facts, authority=stream.AUTHORITIES,
                constructor_configuration=context['configuration'], semantic_iterator=context['method'],
                source_observer=dict(base_test_id=donor['base'], span=donor['file'].span(donor['observer']),
                                     text=donor['file'].text(donor['observer'])),
                original_exception_block=file.span(record['error']),
                body_lengths=[len(value) for value in record['domain']],
                body_sha256=[hashlib.sha256(value).hexdigest() for value in record['domain']],
                byte_concatenation_unchanged=True, complete_original_test_preserved=True),
            oracle_status='declared_total_close_relation_pending_controlled_execution', order=order(record)))
    ranking = sorted(candidates, key=lambda row: (row['order'], row['id']))
    return dict(version=VERSION, status='source_candidates', candidates=ranking[:limit],
                total_candidates=len(ranking), selected=min(limit, len(ranking)), contract=facts,
                source_error_tests=len(errors), source_close_controls=sum(map(len, donors.values())), skipped=skipped)
