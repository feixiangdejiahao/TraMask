"""Source-only priority for exception contexts that may bypass a q writer.

This is a ranking hypothesis, not exception feasibility or oracle validation.
All candidates survive; boolean evidence only partitions a fixed input order.
"""
from __future__ import annotations

import ast
from collections import defaultdict

from experimental.assertion_write_origin import Index, Module


def _shape(node):
    return ast.dump(node, include_attributes=False)


def _contains(outer, inner):
    return (outer['path'] == inner['path'] and outer['start_byte'] <= inner['start_byte']
            and inner['end_byte'] <= outer['end_byte'])


def _overlaps(left, right):
    return (left['path'] == right['path'] and left['start_byte'] < right['end_byte']
            and right['start_byte'] < left['end_byte'])


def _updated_module(corpus, candidate, path):
    data = corpus['sources'][path]['code'].encode()
    edits = sorted((e for e in candidate['edits'] if e['span']['path'] == path),
                   key=lambda e: e['span']['start_byte'])
    end = -1
    for edit in edits:
        span = edit['span']
        if span['start_byte'] < end or data[span['start_byte']:span['end_byte']].decode() != edit['before']:
            raise ValueError('invalid_source_edit')
        end = span['end_byte']
    for edit in reversed(edits):
        span = edit['span']
        data = data[:span['start_byte']] + edit['after'].encode() + data[span['end_byte']:]
    code = data.decode()
    return Module(path, code, ast.parse(code)), edits


def _map_preserved(span, edits):
    if any(_overlaps(span, e['span']) or
           (e['span']['start_byte'] == e['span']['end_byte'] and
            span['start_byte'] < e['span']['start_byte'] < span['end_byte']) for e in edits):
        return None
    offset = sum(len(e['after'].encode()) - (e['span']['end_byte']-e['span']['start_byte'])
                 for e in edits if e['span']['end_byte'] <= span['start_byte'])
    return {**span, 'start_byte': span['start_byte']+offset, 'end_byte': span['end_byte']+offset}


def _map_enclosing(span, edits):
    """Map an existing constructor boundary, permitting only internal edits."""
    for edit in edits:
        changed = edit['span']
        if _overlaps(span, changed) and not _contains(span, changed):
            return None
        if changed['start_byte'] == changed['end_byte'] and changed['start_byte'] in {span['start_byte'], span['end_byte']}:
            return None
    delta = lambda e: len(e['after'].encode())-(e['span']['end_byte']-e['span']['start_byte'])
    start = span['start_byte']+sum(delta(e) for e in edits if e['span']['end_byte'] <= span['start_byte'])
    end = span['end_byte']+sum(delta(e) for e in edits if e['span']['end_byte'] <= span['end_byte'])
    return {**span, 'start_byte': start, 'end_byte': end}


def _same_span(left, right):
    return all(left[k] == right[k] for k in ('path', 'start_byte', 'end_byte'))


def _pytest_symbols(module, candidate):
    symbols = {}
    for node in module.tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == 'pytest':
                    symbols[alias.asname or alias.name] = 'pytest'
        elif isinstance(node, ast.ImportFrom) and node.module == 'pytest' and not node.level:
            for alias in node.names:
                if alias.name == 'raises':
                    symbols[alias.asname or alias.name] = 'raises'
    for row in candidate.get('imports', []):
        if row.get('module') == 'pytest' and row.get('imported_name') in {None, 'raises'}:
            symbols[row['name']] = 'raises' if row.get('imported_name') == 'raises' else 'pytest'
    for node in module.tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign)) else []
        for target in targets:
            for name in ast.walk(target):
                if isinstance(name, ast.Name):
                    symbols.pop(name.id, None)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.pop(node.name, None)
    return symbols


def _handlers(module, function, symbols):
    # A lexical shadow is enough to withhold evidence. The ranking does not
    # claim to resolve arbitrary runtime monkeypatching of the test framework.
    shadowed = {n.id for n in ast.walk(function) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
    shadowed.update(n.arg for n in ast.walk(function) if isinstance(n, ast.arg))
    for node in ast.walk(function):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            shadowed.update(a.asname or a.name.split('.')[0] for a in node.names)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node is not function:
            shadowed.add(node.name)
    result = []
    for node in ast.walk(function):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            expr = item.context_expr
            if not isinstance(expr, ast.Call):
                continue
            func = expr.func
            valid = (isinstance(func, ast.Name) and symbols.get(func.id) == 'raises' and func.id not in shadowed)
            valid |= (isinstance(func, ast.Attribute) and func.attr == 'raises'
                      and isinstance(func.value, ast.Name) and func.value.id not in shadowed
                      and symbols.get(func.value.id) == 'pytest')
            if valid:
                result.append(node)
                break
    return result


def _owner(module, span):
    nodes = [n for n in ast.walk(module.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and _contains(module.span(n), span)]
    return min(nodes, key=lambda n: n.end_lineno-n.lineno) if nodes else None


def evidence(corpus, candidate, assertions, *, index=None):
    """Match a new source handler to a same-binding syntactic writer path."""
    if corpus.get('language') != 'python':
        return []
    index = index or Index(corpus['sources'])
    rows, modules = [], {}
    for assertion in assertions:
        q = assertion['span']
        try:
            if q['path'] not in modules:
                old_code = corpus['sources'][q['path']]['code']
                before = Module(q['path'], old_code, ast.parse(old_code))
                after, edits = _updated_module(corpus, candidate, q['path'])
                modules[q['path']] = before, after, edits
            before, after, edits = modules[q['path']]
            mapped = _map_preserved(q, edits)
            if mapped is None:
                continue
            old_owner, new_owner = _owner(before, q), _owner(after, mapped)
            if old_owner is None or new_owner is None:
                continue
            old_handlers = _handlers(before, old_owner, _pytest_symbols(before, {}))
            new_handlers = _handlers(after, new_owner, _pytest_symbols(after, candidate))
        except (ValueError, KeyError, SyntaxError):
            continue
        for read in assertion.get('analysis', {}).get('reads', []):
            if read.get('status') != 'statically_bound_partial_slice':
                continue
            expression = ast.parse(read['expression'], mode='eval').body
            if not isinstance(expression, ast.Attribute) or not isinstance(expression.value, ast.Name):
                continue
            actual_q = next((n for n in ast.walk(new_owner) if isinstance(n, ast.Assert)
                             and _same_span(after.span(n), mapped)), None)
            allocation = _map_enclosing(read['binding']['allocation_span'], edits)
            if actual_q is None or allocation is None:
                continue
            binding, error = index.bind_object(after, new_owner, expression.value.id, actual_q.lineno)
            if error or binding['class_id'] != read['binding']['class_id'] or not _same_span(binding['allocation_span'], allocation):
                continue
            paths = read['writer_paths']
            initialized = {p['writer_method'] for p in paths if p['root']['kind'] == 'construction'}
            for path in paths:
                root = path['root']
                if root['kind'] != 'test_operation':
                    continue
                # Need a separately located initialization writer, and a
                # possible exceptional exit on the route to the later writer.
                if not any(w['method'] in initialized and w['method'] != path['writer_method'] for w in read['writers']):
                    continue
                bypass = [s for edge in path['calls'] for s in edge.get('possible_bypass_sites', [])]
                # A writer is the terminal program point even when it is in
                # the operation method itself (a zero-call-edge path). Apply
                # the same source-level may-exit predicate to that final leg;
                # extracting/inlining a self helper must not hide this evidence.
                # This still does not establish exception feasibility or q reachability.
                bypass.extend(s for writer in read['writers']
                              if writer['method'] == path['writer_method']
                              for s in writer.get('possible_bypass_sites', []))
                if not bypass:
                    continue
                old_call = next((n for n in ast.walk(old_owner) if isinstance(n, ast.Call)
                                 and before.span(n)['start_byte'] == root['span']['start_byte']
                                 and before.span(n)['end_byte'] == root['span']['end_byte']), None)
                if old_call is None or any(_contains(before.span(h), root['span']) for h in old_handlers):
                    continue
                calls = [n for n in ast.walk(new_owner) if isinstance(n, ast.Call)
                         and _shape(n.func) == _shape(old_call.func)
                         and after.span(n)['end_byte'] <= mapped['start_byte']
                         and any(_contains(after.span(h), after.span(n))
                                 and after.span(h)['end_byte'] <= mapped['start_byte'] for h in new_handlers)]
                if len(calls) != 1:
                    continue
                new_call = calls[0]
                operation_binding, error = index.bind_object(after, new_owner, new_call.func.value.id, new_call.lineno)
                if error or operation_binding['object_binding'] != binding['object_binding']:
                    continue
                handlers = [h for h in new_handlers if _contains(after.span(h), after.span(new_call))
                            and after.span(h)['end_byte'] <= mapped['start_byte']]
                if not handlers:
                    continue
                rows.append(dict(source_q=q, source_binding=read['binding'], field=read['storage_field'],
                    source_operation=root['span'], modified_operation=after.span(new_call),
                    new_handler=after.span(handlers[0]), writer_method=path['writer_method'],
                    writer_sites=[w['span'] for w in read['writers'] if w['method'] == path['writer_method']],
                    possible_bypass_sites=bypass,
                    status='source_may_bypass_priority_not_execution_or_oracle_proof',
                    unknown=read.get('unknown', [])))
    return rows


def prioritize(corpus, candidates, census):
    index = Index(corpus['sources'])
    by_test = defaultdict(list)
    for assertion in census['assertions']:
        for test_id in assertion['test_ids']:
            by_test[test_id].append(assertion)
    records = [dict(id=c['id'], original_rank=i+1,
                    evidence=evidence(corpus, c, by_test[c['base_test_id']], index=index))
               for i, c in enumerate(candidates)]
    ranked = sorted(records, key=lambda r: (not bool(r['evidence']), r['original_rank']))
    for rank, row in enumerate(ranked, 1):
        row['rank'] = rank
    return dict(ranking=ranked, input_count=len(candidates),
                supported_candidates=sum(bool(r['evidence']) for r in records),
                selection='stable boolean partition; no candidates discarded',
                provider_calls=0, subject_executions=0)
