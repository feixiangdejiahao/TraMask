"""Local-only receipt localization; no provider, execution, or validity decision.

Unlike census_source_failure_evidence (a source-only Go adapter census), this
experiment consumes native receipt locations. It never sends diagnostic text to
a model. A unique reported source site is not proof of the first causal failure.
Only the controlled_failures array of a supplied baseline is decoded.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relation_search.admission import program_candidate
from relation_search.compact_test_obligations import analyze as compact_analysis, source_text

VERSION = 'reported-python-assertion-localization.v2'
SAMPLE_SALT = 'failure-localization-fixed-sample-v1'
LIMITATIONS = [
    'reported source location only; first failure and causal prefix are not proved',
    'receipt text is used locally for location matching, never as an oracle',
    'no dynamic helper invocation, parameter value, or alias identity is recovered',
    'lexical prefix is not a complete causal slice or a validated test',
    'a reported assertion-containing statement does not prove operand normal completion or its own predicate failure',
    'question byte estimates exclude issue text and external fixture/helper context',
    'alarm soundness and complete-test validity are unassessed',
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def controlled_failures(text):
    """Decode exactly one allowed top-level value; skip all other value bytes."""
    decoder = json.JSONDecoder()

    def whitespace(index):
        while index < len(text) and text[index].isspace():
            index += 1
        return index

    def end_value(index):
        stack, quoted, escaped = [], False, False
        for pos in range(index, len(text)):
            char = text[pos]
            if quoted:
                if escaped:
                    escaped = False
                elif char == '\\':
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char in '[{':
                stack.append(char)
            elif char in ']}':
                if not stack:
                    return pos
                if stack.pop() != {']': '[', '}': '{'}[char]:
                    raise ValueError('malformed baseline nesting')
            elif char == ',' and not stack:
                return pos
        raise ValueError('unterminated baseline value')

    pos = whitespace(0)
    if text[pos:pos + 1] != '{':
        raise ValueError('baseline must be an object')
    pos, found = whitespace(pos + 1), None
    while text[pos:pos + 1] != '}':
        key, pos = decoder.raw_decode(text, pos)
        pos = whitespace(pos)
        if not isinstance(key, str) or text[pos:pos + 1] != ':':
            raise ValueError('malformed baseline key')
        start = whitespace(pos + 1)
        pos = end_value(start)
        if key == 'controlled_failures':
            if found is not None:
                raise ValueError('duplicate controlled_failures')
            found = json.loads(text[start:pos])
        pos = whitespace(pos)
        if text[pos:pos + 1] == ',':
            pos = whitespace(pos + 1)
        elif text[pos:pos + 1] != '}':
            raise ValueError('malformed baseline separator')
    if not isinstance(found, list):
        raise ValueError('missing controlled_failures array')
    return found


def sample(records, limit):
    """Source identity alone fixes selection before any receipt is inspected."""
    unique = {}
    for record in sorted(records, key=lambda row: row['key']):
        unique.setdefault((record['case'], record['candidate_id']), record)
    ranked = sorted(unique.items(), key=lambda item: (
        digest((SAMPLE_SALT + '\0' + '\0'.join(item[0])).encode()), item[0]))
    return [record for _, record in ranked[:limit]], len(unique)


def offsets(code):
    result = [0]
    for line in code.splitlines(keepends=True):
        result.append(result[-1] + len(line.encode()))
    return result


def extent(node, path, starts, version):
    return dict(path=path, start_byte=starts[node.lineno - 1] + node.col_offset,
                end_byte=starts[node.end_lineno - 1] + node.end_col_offset,
                line=node.lineno, end_line=node.end_lineno, version=version)


def parents(tree):
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


def containing_function(node, ancestry):
    while node in ancestry:
        node = ancestry[node]
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            return node
    return None


def locations(detail):
    """Only traceback-frame/terminal location syntax; never parse expected values."""
    rows = []
    for match in re.finditer(r'(?m)^\s*File "([^"\n]+\.py)", line (\d+), in ([^\n]+)\s*$', detail):
        rows.append(dict(path=match[1], line=int(match[2]), origin='python_frame', function=match[3].strip()))
    for match in re.finditer(r'(?m)^\s*([^\s:\n][^:\n]*\.py):(\d+):(?:\d+:)?\s*AssertionError(?:\s*:.*)?\s*$', detail):
        rows.append(dict(path=match[1].strip(), line=int(match[2]), origin='pytest_assertion_terminal'))
    return list({(r['path'], r['line'], r.get('function')): r for r in rows}.values())


def normalize_owner(corpus, candidate):
    selected = corpus['tests'][candidate['base_test_id']]
    path = selected['span']['path']
    original = corpus['sources'][path]['code']
    data = original.encode()
    edits = sorted(candidate.get('edits', []), key=lambda row: (row['span']['start_byte'], row['span']['end_byte']))
    previous = -1
    for edit in edits:
        at = edit['span']
        if (at['path'] != path or not selected['span']['start_byte'] <= at['start_byte'] <= at['end_byte'] <= selected['span']['end_byte']
                or at['start_byte'] < previous or data[at['start_byte']:at['end_byte']].decode() != edit['before']):
            raise ValueError('candidate source edit mismatch')
        previous = at['end_byte']
    for edit in reversed(edits):
        at = edit['span']
        data = data[:at['start_byte']] + edit['after'].encode() + data[at['end_byte']:]
    original_tree = ast.parse(original)
    starts = offsets(original)
    definition = selected.get('definition_span', selected['span'])
    original_roots = [node for node in original_tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and extent(node, path, starts, 'original')['start_byte'] == definition['start_byte']]
    if len(original_roots) != 1:
        raise ValueError('original top-level root not unique')
    tree = ast.parse(data.decode())
    roots = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == original_roots[0].name]
    if len(roots) != 1:
        raise ValueError('normalized top-level root not unique')
    return path, data.decode(), tree, roots[0]


def locate(detail, emitted, test_name, normalized, root, *, parameterized=False, candidate_path=None):
    """Map a unique native line to an emitted assert, then unique root AST site."""
    result = dict(version=VERSION, status='unknown', reason=None, limitations=LIMITATIONS,
                  first_failure_proved=False, causal_prefix_proved=False,
                  alarm_soundness='unassessed', complete_test_validity='unassessed')
    frames = locations(detail)
    if not frames:
        return dict(result, reason='no_supported_python_location')
    candidates = {}
    parsed = {}
    for frame in frames:
        paths = [path for path in emitted if frame['path'] == path or frame['path'].endswith('/' + path)]
        if len(paths) != 1:
            continue
        path = paths[0]
        if path not in parsed:
            tree = ast.parse(emitted[path])
            parsed[path] = tree, parents(tree), offsets(emitted[path])
        tree, ancestry, starts = parsed[path]
        generated_roots = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.name == test_name]
        if (candidate_path is None or path == candidate_path) and len(generated_roots) != 1:
            return dict(result, reason='generated_test_definition_not_unique')
        sites = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)
                 and node.lineno <= frame['line'] <= node.end_lineno]
        for node in sites:
            owner = containing_function(node, ancestry)
            if frame.get('function') and frame['function'] != getattr(owner, 'name', None):
                return dict(result, reason='traceback_function_source_mismatch')
            at = extent(node, path, starts, 'emitted')
            key = (path, at['start_byte'], at['end_byte'])
            candidates[key] = (node, owner, ancestry, at)
    if not candidates:
        return dict(result, reason='reported_location_not_a_source_assertion')
    if len(candidates) != 1:
        return dict(result, reason='multiple_reported_assertion_sites', site_count=len(candidates))
    node, owner, ancestry, at = next(iter(candidates.values()))
    result['emitted_assertion'] = at
    if candidate_path is not None and at['path'] != candidate_path:
        return dict(result, reason='assertion_outside_candidate_emitted_path')
    if owner is None or getattr(owner, 'name', None) != test_name:
        return dict(result, reason='helper_or_other_test_assertion')
    if not isinstance(ancestry.get(owner), ast.Module):
        return dict(result, reason='non_module_test_scope')
    if isinstance(owner, ast.AsyncFunctionDef) or isinstance(root, ast.AsyncFunctionDef):
        return dict(result, reason='async_root')
    if any(isinstance(n, (ast.Await, ast.Yield, ast.YieldFrom, ast.AsyncFor, ast.AsyncWith)) for n in ast.walk(owner)):
        return dict(result, reason='async_or_generator_context')
    path, code, tree = normalized
    ancestry = parents(tree)
    normalized_sites = [n for n in ast.walk(root) if isinstance(n, ast.Assert)
                        and containing_function(n, ancestry) is root
                        and ast.dump(n, include_attributes=False) == ast.dump(node, include_attributes=False)]
    if len(normalized_sites) != 1:
        return dict(result, reason='normalized_assertion_missing_or_ambiguous', site_count=len(normalized_sites))
    site = normalized_sites[0]
    starts = offsets(code)
    normalized_at = extent(site, path, starts, 'normalized')
    root_at = extent(root, path, starts, 'normalized')
    context, cursor = [], site
    while cursor is not root:
        cursor = ancestry[cursor]
        if cursor is not root:
            context.append(type(cursor).__name__)
    blockers = []
    if parameterized or root.decorator_list:
        blockers.append('decorator_or_runtime_parameter_context')
    if any(kind in context for kind in ('Try', 'TryStar', 'With', 'AsyncWith')):
        blockers.append('exception_or_context_manager_region')
    if any(kind in context for kind in ('For', 'While', 'AsyncFor')):
        blockers.append('repeated_site_runtime_instance_unknown')
    prefix = code.encode()[root_at['start_byte']:normalized_at['end_byte']].decode()
    statement = code.encode()[normalized_at['start_byte']:normalized_at['end_byte']].decode()
    return dict(result, status='source_site_located_context_unknown' if blockers else 'localized_root_assertion',
                reason=None, normalized_assertion=normalized_at, root=root_at,
                normalized_predicate=extent(site.test, path, starts, 'normalized'),
                predicate_text=ast.get_source_segment(code, site.test),
                statement=statement, lexical_contexts=list(reversed(context)), context_unknowns=blockers,
                prefix=dict(ref=dict(root_at, end_byte=normalized_at['end_byte'], end_line=normalized_at['end_line']),
                            code=prefix, kind='lexical_prefix_not_proved_causal_slice'),
                whole_root_bytes=root_at['end_byte'] - root_at['start_byte'], prefix_bytes=len(prefix.encode()))


def attach_q(result, graph):
    if 'normalized_assertion' not in result:
        return result
    target = result['normalized_predicate']
    matches = []
    for ident, site in graph.get('obligations', {}).items():
        ref = site.get('predicate')
        if not ref:
            continue
        block = graph['sources'][ref['source']]
        if (site['unit'] == graph['root'] and block['path'] == target['path']
                and block['start_byte'] + ref['start'] == target['start_byte']
                and block['start_byte'] + ref['end'] == target['end_byte']):
            matches.append((ident, site, source_text(graph, ref)))
    if len(matches) != 1:
        return dict(result, status='source_site_located_context_unknown', reason='compact_q_missing_or_ambiguous')
    ident, site, predicate = matches[0]
    if predicate != result['predicate_text']:
        return dict(result, status='source_site_located_context_unknown', reason='compact_predicate_source_mismatch')
    result = dict(result, compact_q=dict(id=ident, unit=site['unit'], kind=site['kind'],
        predicate=predicate, guards=site.get('guards', []), exception_regions=site.get('exception_regions', [])),
        compact_source_status=graph['status'])
    # This proposed source-only question is an estimate, never dispatched here.
    question = dict(scope='justify_reported_assertion_at_this_source_site_not_complete_test',
        predicate=predicate, statement=result['statement'], lexical_prefix=result['prefix']['code'],
        lexical_contexts=result['lexical_contexts'], limitations=LIMITATIONS,
        setup_and_external_effects='must_be_justified_separately', later_checks='not_adjudicated',
        requested_judgment='contract-justified behavior at this statement, including errors during operand evaluation',
        runtime_values_and_messages='not supplied')
    result['question_estimate_bytes'] = len(canonical(question))
    result['source_question'] = question
    return result


def verified(receipt, cache):
    path = receipt['path']
    if path not in cache:
        raw = Path(path).read_bytes()
        cache[path] = raw, digest(raw), None
    raw, actual, parsed = cache[path]
    if actual != receipt['sha256']:
        raise ValueError('frozen input SHA mismatch')
    if parsed is None:
        parsed = json.loads(raw)
        cache[path] = raw, actual, parsed
    return parsed


def emitted_files(manifest, candidate_id):
    obligations = [row for row in manifest['obligations'] if row.get('candidate_id') == candidate_id]
    phases = [row for row in manifest.get('phases', []) if row['role'] == 'generated']
    if len(obligations) != 1 or len(phases) != 1:
        raise ValueError('candidate generated phase/obligation not unique')
    mounts = {row['target']: row for row in manifest['mounts']}
    sources, provenance = {}, []
    for row in phases[0]['files']:
        mount = mounts[row['staged']]
        raw = Path(mount['source']).read_bytes()
        if digest(raw) != row['sha256'] or mount['sha256'] != row['sha256']:
            raise ValueError('emitted snapshot SHA mismatch')
        sources[row['target']] = raw.decode()
        provenance.append(dict(target=row['target'], snapshot=mount['source'], sha256=row['sha256']))
    if obligations[0]['path'] not in sources:
        raise ValueError('candidate obligation path absent from snapshots')
    return sources, obligations[0], provenance


def process(record, cache):
    corpus = verified(record['inputs']['corpus'], cache)
    if corpus['language'] != 'python':
        return dict(status='unknown', reason='non_python_scope', language=corpus['language']), {}
    frontend = verified(record['inputs']['frontend'], cache)
    candidates = verified(record['inputs']['candidates'], cache)
    candidate = program_candidate(next(row for row in candidates if row['id'] == record['candidate_id']))
    failures, audit = [], dict(native_receipts=[], raw_diagnostic_text_local_only=True)
    for receipt in record['native_evidence']:
        manifest = verified(receipt['manifest'], cache)
        report = verified(receipt['result'], cache)
        if report.get('errors'):
            raise ValueError('native report has harness errors')
        emitted, obligation, snapshots = emitted_files(manifest, candidate['id'])
        names = set(receipt['test_ids'])
        if obligation['id'] not in names:
            raise ValueError('native declared test differs from candidate obligation')
        tests = [row for row in report['tests'] if any(
            row['id'] == name or row['id'].endswith('::' + name)
            or row['id'].rsplit('::', 1)[-1].startswith(name + '[') for name in names)]
        for test in tests:
            if test['status'] != 'fail':
                continue
            detail = test.get('detail', test.get('message', ''))
            failures.append((detail, emitted, obligation, '[' in test['id']))
            audit['native_receipts'].append(dict(result=receipt['result'], manifest=receipt['manifest'],
                runtime_id=test['id'], diagnostic_sha256=digest(detail.encode()),
                locations=locations(detail), emitted_snapshots=snapshots))
    if len(failures) != 1:
        return dict(status='unknown', reason='failed_runtime_instance_not_unique', failed_instances=len(failures)), audit
    path, code, tree, root = normalize_owner(corpus, candidate)
    detail, emitted, obligation, parameterized = failures[0]
    result = locate(detail, emitted, obligation['test_name'], (path, code, tree), root,
                    parameterized=parameterized, candidate_path=obligation['path'])
    audit['normalized_owner_sha256'] = digest(code.encode())
    audit['candidate_sha256'] = digest(canonical(candidate))
    if 'normalized_assertion' in result:
        graph = compact_analysis(corpus, frontend, candidate)
        result = attach_q(result, graph)
        audit['compact_graph'] = graph
        if candidate.get('imports'):
            result['context_unknowns'].append('candidate_added_imports')
            result['status'] = 'source_site_located_context_unknown'
    return result, audit


def write(path, value):
    with path.open('xb') as stream:
        stream.write(canonical(value) + b'\n')


def run(baseline, output, *, limit=100):
    if not 1 <= limit <= 1438:
        raise ValueError('sample limit must be between 1 and 1438')
    raw = Path(baseline).read_bytes()
    records = controlled_failures(raw.decode())
    chosen, population = sample(records, limit)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    module_path = Path(__file__).resolve()
    code_sha = digest(module_path.read_bytes())
    imported = {str(Path(module.__file__).resolve()): digest(Path(module.__file__).read_bytes())
                for module in tuple(sys.modules.values()) if getattr(module, '__file__', None)
                and Path(module.__file__).suffix == '.py'
                and Path(module.__file__).resolve().is_relative_to(ROOT)
                and '.venv' not in Path(module.__file__).parts}
    protocol = dict(version=VERSION, baseline=dict(path=str(Path(baseline).resolve()), sha256=digest(raw)),
        script_sha256=code_sha, imported_source_sha256=imported,
        sample_salt=SAMPLE_SALT, raw_occurrences=len(records), distinct_candidates=population,
        sample_count=len(chosen), selection='lowest SHA256(salt,NUL,case,NUL,candidate_id); first occurrence by key',
        selected=[dict(key=row['key'], case=row['case'], candidate_id=row['candidate_id']) for row in chosen],
        ignored_baseline_values='all top-level values except controlled_failures were skipped without decoding',
        provider_calls=0, native_executions=0, validity_labels_read=False, limitations=LIMITATIONS)
    write(output / 'protocol.json', protocol)
    started, cache, rows = time.monotonic(), {}, []
    for index, record in enumerate(chosen):
        item_started = time.monotonic()
        try:
            result, audit = process(record, cache)
        except (ValueError, KeyError, TypeError, SyntaxError, StopIteration, OSError, RecursionError) as error:
            result, audit = dict(status='unknown', reason='source_or_receipt_unavailable', error_type=type(error).__name__), dict(local_error=str(error))
        directory = output / ('item_' + str(index).zfill(4))
        directory.mkdir()
        write(directory / 'source_localization.json', result)
        write(directory / 'local_receipt_audit.json', audit)
        row = dict(candidate_key=record['key'], candidate_id=record['candidate_id'], status=result['status'],
            reason=result.get('reason'), elapsed_seconds=round(time.monotonic() - item_started, 4),
            normalized_site_found='normalized_assertion' in result, compact_q_found='compact_q' in result,
            prefix_bytes=result.get('prefix_bytes'), whole_root_bytes=result.get('whole_root_bytes'),
            question_estimate_bytes=result.get('question_estimate_bytes'), context_unknowns=result.get('context_unknowns', []),
            artifact=str(directory.relative_to(output)))
        rows.append(row)
        print(json.dumps(dict(completed=index + 1, status=row['status'], reason=row['reason'])), flush=True)
    assert digest(module_path.read_bytes()) == code_sha, 'script changed during census'
    assert all(digest(Path(path).read_bytes()) == checksum for path, checksum in imported.items()), 'imported source changed during census'
    write(output / 'rows.json', rows)
    summary = dict(version=VERSION, sample_count=len(rows), elapsed_seconds=round(time.monotonic() - started, 3),
        status_counts=dict(Counter(row['status'] for row in rows)), reason_counts=dict(Counter(row['reason'] for row in rows if row['reason'])),
        normalized_sites=sum(row['normalized_site_found'] for row in rows), compact_q_sites=sum(row['compact_q_found'] for row in rows),
        total_prefix_bytes=sum(row['prefix_bytes'] or 0 for row in rows), total_root_bytes=sum(row['whole_root_bytes'] or 0 for row in rows),
        total_question_estimate_bytes=sum(row['question_estimate_bytes'] or 0 for row in rows),
        limitations=LIMITATIONS, provider_calls=0, native_executions=0, alarm_soundness='not_evaluated', complete_test_validity='not_evaluated')
    write(output / 'summary.json', summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    print(json.dumps(run(args.baseline, args.output, limit=args.limit), indent=2))
