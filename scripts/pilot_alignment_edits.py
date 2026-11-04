#!/usr/bin/env python3
"""Freeze public-source local edits, then execute original checks on P and R."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from eviweave.anchors import _parser
from eviweave.artifacts import read_json, write_json
from eviweave.local_edits import LocalEditIndex, apply_edits
from eviweave.test_units import discover
from pilot_behavior_alignment import public_sources, STUDY, FR


ENTRIES = {
    'S006': {'source': 'H:s57_c0:0005', 'range': [3651, 3691], 'rule': 'deletion_plans',
             'runner': 'jest', 'workdir': '/app'},
    'S041': {'source': 'H:s53_c0:0011', 'range': [10980, 10987], 'rule': 'fresh_object_plans',
             'runner': 'vitest', 'workdir': '/app/packages/core'},
}
BUDGET = 8


def runner_command(entry, destination, test_name):
    path = str(Path(destination).relative_to(entry['workdir']))
    pattern = re.escape(test_name.split(' > ')[-1])
    if entry['runner'] == 'jest':
        arguments = ['./node_modules/.bin/jest', '--runTestsByPath', path, '--runInBand',
                     '--testNamePattern', pattern, '--json', '--transform', json.dumps({
                         r'^.+\.tsx?$': ['ts-jest', {'useESM': True, 'diagnostics': False, 'isolatedModules': True}],
                         r'^.+\.m?jsx?$': 'babel-jest'})]
    else:
        arguments = ['./node_modules/.bin/vitest', 'run', path, '-t', pattern, '--reporter=json',
                     '--maxWorkers=1', '--no-file-parallelism']
    return shlex.join(arguments)


def generate(out):
    out.mkdir(parents=True)
    protocol = read_json(STUDY/'protocol.json')
    cases = {c['screen_id']: c for c in read_json(FR/'cases.json')['cases']}
    code = out/'code'
    code.mkdir()
    for path in ['src/eviweave/local_edits.py', 'src/eviweave/evidence.py', 'src/eviweave/behavior.py',
                 'src/eviweave/anchors.py', 'scripts/pilot_alignment_edits.py',
                 'scripts/pilot_behavior_alignment.py', 'scripts/verify_pre_slice_five_pilot.py']:
        (code/Path(path).name).write_bytes((ROOT/path).read_bytes())
    write_json(out/'protocol.json', {'entries': ENTRIES, 'execution_budget_per_task': BUDGET,
                                   'candidate_order': 'source-coordinate order; duplicate syntax merges provenance',
                                   'reference_access': 'only after generation has frozen all candidate bytes',
                                   'new_model_requests': 0,
                                   'scope': 'controlled-entry local-edit executability, not complete search or an 88-task success rate'})
    summaries = []
    for sid, entry in ENTRIES.items():
        case = next(c for c in protocol['cases'] if c['case'] == sid)
        sources, metadata = public_sources(case, cases)
        index = LocalEditIndex(sources)
        plans = getattr(index, entry['rule'])(entry['source'], entry['range'])
        graph, _ = sources[entry['source']]
        units = discover(graph.source['path'], graph.raw)
        selected = [u for u in units['units'] if units['ranges'][u['id']][0] <= entry['range'][0]
                    and entry['range'][1] <= units['ranges'][u['id']][1]]
        if len(selected) != 1:
            raise ValueError('The controlled entry must belong to exactly one named test')
        unit = selected[0]
        directory = out/'cases'/sid
        directory.mkdir(parents=True)
        baseline = directory/'baseline.ts'
        baseline.write_bytes(graph.raw)
        input_sources = []
        for number, (source, (source_graph, _)) in enumerate(sources.items()):
            filename = f'input_{number:03}{Path(source_graph.source["path"]).suffix}'
            (directory/filename).write_bytes(source_graph.raw)
            input_sources.append({'source': source, 'file': filename, **metadata[source]})
        executions = [{'id': 'baseline', 'file': str(baseline.resolve()), 'edits': [],
                       'sha256': hashlib.sha256(graph.raw).hexdigest(), 'parse_status': 'parsed'}]
        for candidate in plans['candidates'][:BUDGET]:
            raw = apply_edits(graph.raw, candidate['edits'])
            parsed = _parser(Path(graph.source['path']).suffix).parse(raw).root_node
            candidate['parse_status'] = 'source_parse_error' if parsed.has_error else 'parsed'
            filename = directory/(candidate['id']+'.ts')
            filename.write_bytes(raw)
            executions.append({**candidate, 'file': str(filename.resolve())})
        command = runner_command(entry, graph.source['path'], unit['name'])
        record = {**plans, 'case': sid, 'input_sources': input_sources, 'test': unit,
                  'destination': graph.source['path'], 'workdir': entry['workdir'], 'command': command,
                  'executions': executions, 'execution_budget': BUDGET,
                  'candidates_selected': min(BUDGET, plans['total_candidates']),
                  'candidates_not_executed_due_to_budget': max(0, plans['total_candidates']-BUDGET),
                  'source_only_generation': True, 'reference_material_read_during_generation': False}
        write_json(directory/'plans.json', record)
        summaries.append({'case': sid, 'recipes': len(plans['recipes']), 'total_candidates': plans['total_candidates'],
                          'selected_candidates': record['candidates_selected'],
                          'budget_tail': record['candidates_not_executed_due_to_budget'],
                          'parse_statuses': dict(Counter(c['parse_status'] for c in executions)), 'test': unit['name']})
        print('frozen', sid, summaries[-1], flush=True)
    write_json(out/'generation.json', {'cases': summaries, 'new_model_requests': 0,
                                      'frozen_before_reference_access': True})


def named_report(output, expected_name):
    decoder = json.JSONDecoder()
    reports = []
    for match in re.finditer(r'(?m)^\s*\{', output):
        try:
            item, _ = decoder.raw_decode(output[match.end()-1:])
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and 'testResults' in item:
            reports.append(item)
    if len(reports) != 1:
        return {'status': 'named_report_unavailable', 'reports_found': len(reports)}
    report = reports[0]
    assertions = [test for suite in report['testResults'] for test in suite['assertionResults']]
    active = [test for test in assertions if test['status'] in {'passed', 'failed'}]
    leaf = expected_name.split(' > ')[-1]
    target = [test for test in active if test['title'] == leaf]
    return {'status': 'named_test_observed' if len(active) == len(target) == 1 else 'named_test_attribution_unresolved',
            'active_tests': len(active), 'expected_test': expected_name, 'observed': target,
            'runner_report': report}


def project_named_test(raw, path, test_name):
    """Keep original imports and the complete named registration verbatim.

    This explicit execution projection rejects unresolved free names and known
    surrounding fixture hooks. It is not a general test isolation algorithm.
    """
    from eviweave.evidence import SourceGraph
    units = discover(path, raw)
    unit, = [u for u in units['units'] if u['name'] == test_name]
    a, b = units['ranges'][unit['id']]
    original = SourceGraph({'id': 'original_test', 'path': path, 'raw': raw})
    containing = [s for s in original.scopes if s['ast'].start_byte <= a and b <= s['ast'].end_byte]
    scopes = {s['id'] for s in containing}
    hooks = [(name, node['start']) for node in original.nodes if node['scope'] in scopes
             for name, _, _ in node['calls'] if name in {'beforeEach', 'beforeAll', 'afterEach', 'afterAll'}]
    if hooks:
        raise ValueError('Named test projection has surrounding fixture hooks: ' + repr(hooks))
    imports = [[n.start_byte, n.end_byte] for n in original.root.named_children if n.type == 'import_statement']
    ranges = [*imports, [a, b]]
    projected = b'\n\n'.join(raw[start:end] for start, end in ranges) + b'\n'
    graph = SourceGraph({'id': 'projected_test', 'path': path, 'raw': projected})
    if graph.issues:
        raise ValueError('Projected test is not syntactically valid: ' + repr(graph.issues))
    builtins = {'it', 'test', 'expect', 'describe', 'Promise', 'Math', 'setTimeout', 'clearTimeout'}
    identifiers, pending = set(), [graph.root]
    while pending:
        node = pending.pop()
        if node.type in {'identifier', 'shorthand_property_identifier'}:
            identifiers.add(graph.text(node))
        pending.extend(node.named_children)
    unresolved = sorted({name for node in graph.nodes for scope, name in node['uses']
                         if scope == 0 and name in identifiers and not graph.definitions[scope, name] and name not in builtins})
    if unresolved:
        raise ValueError('Named test projection has unresolved free names: ' + repr(unresolved))
    return projected, {'test': test_name, 'retained_ranges': ranges, 'entire_target_registration_retained': True,
                       'surrounding_fixture_hooks': hooks, 'unresolved_free_names': unresolved,
                       'source_sha256': hashlib.sha256(raw).hexdigest(), 'sha256': hashlib.sha256(projected).hexdigest()}


def evaluate(out, candidate_run=None, reason=None, cases=None, project=False):
    # Only evaluation imports the helper that reads and applies solution.patch.
    from evaluate_composition_plans import prepare_reference, source_paths
    from eviweave.execution import run_in_checkpoint
    candidate_run = candidate_run or out
    cases = cases or list(ENTRIES)
    generation = read_json(candidate_run/'generation.json')
    if candidate_run != out:
        out.mkdir(parents=True)
        (out/'code').mkdir()
        (out/'code'/'pilot_alignment_edits.py').write_bytes(Path(__file__).read_bytes())
        write_json(out/'evaluation_protocol.json', {
            'frozen_candidate_run': str(candidate_run), 'reason': reason,
            'candidates_regenerated': False, 'candidate_bytes_modified': False,
            'execution_projection': 'imports plus verbatim complete target registration' if project else 'full historical file',
            'typescript_execution': 'ts-jest isolated transpilation, diagnostics disabled on P and R',
            'typechecking_not_measured': True,
            'prior_attempt_metric_note': 'r01 new_product_test_runs counted runner invocations; zero named tests were reached'})
    for sid in cases:
        _, status = prepare_reference(sid, out)
        if status != 'ready':
            raise RuntimeError(f'Reference checkpoint preparation failed for {sid}: {status}')
    assessments = []
    for sid in cases:
        plans = read_json(candidate_run/'cases'/sid/'plans.json')
        command = runner_command(ENTRIES[sid], plans['destination'], plans['test']['name'])
        pointers = {'P': read_json(FR/'cases'/sid/'checkpoint.json'),
                    'R': read_json(out/'references'/sid/'checkpoint.json')}
        observed_paths = sorted(set(source_paths(sid)) | {plans['destination']})
        for candidate in plans['executions']:
            installed_file = candidate['file']
            if project:
                projected, projection = project_named_test(Path(candidate['file']).read_bytes(), plans['destination'], plans['test']['name'])
                projection_directory = out/'cases'/sid/'projections'
                projection_directory.mkdir(parents=True, exist_ok=True)
                installed_file = projection_directory/(candidate['id']+'.ts')
                installed_file.write_bytes(projected)
                write_json(projection_directory/(candidate['id']+'.json'), projection)
            for implementation, pointer in pointers.items():
                directory = out/'cases'/sid/'executions'/candidate['id']/implementation
                if candidate['parse_status'] != 'parsed':
                    assessment = {'case': sid, 'candidate': candidate['id'], 'implementation': implementation,
                                  'status': 'candidate_source_parse_error', 'executed': False}
                    write_json(directory/'assessment.json', assessment)
                    assessments.append(assessment)
                    continue
                result = run_in_checkpoint({k: pointer[k] for k in ('image_id', 'head')}, command, directory,
                                           workdir=plans['workdir'], timeout=180, source_paths=observed_paths,
                                           files=[(installed_file, plans['destination'])])
                execution = result['execution']
                output = Path(execution['output']).read_text(errors='replace')
                named = named_report(output, plans['test']['name'])
                assessment = {'case': sid, 'candidate': candidate['id'], 'implementation': implementation,
                              'status': result['status'], 'executed': True, 'returncode': execution['returncode'],
                              'source_unchanged': result['sources']['unchanged'], 'named': named,
                              'exit_code_is_not_bug_verdict': True}
                write_json(directory/'assessment.json', assessment)
                assessments.append(assessment)
                print('executed', sid, candidate['id'], implementation, execution['returncode'], named['status'], flush=True)
    pairs = []
    indexed = {(a['case'], a['candidate'], a['implementation']): a for a in assessments}
    for sid in cases:
        plans = read_json(candidate_run/'cases'/sid/'plans.json')
        for candidate in plans['executions']:
            left, right = [indexed[sid, candidate['id'], implementation] for implementation in ('P', 'R')]
            attributable = all(a['executed'] and a['source_unchanged'] and a['named']['status'] == 'named_test_observed'
                               for a in (left, right))
            statuses = ([a['named']['observed'][0]['status'] for a in (left, right)] if attributable else None)
            pairs.append({'case': sid, 'candidate': candidate['id'], 'edits': candidate['edits'],
                          'attributed_original_test': attributable, 'P_R_test_status': statuses,
                          'differential_failure': statuses == ['failed', 'passed'],
                          'interpretation': 'preserved_original_checks; oracle_applicability_requires_contract_review'})
    summary = {'generation': generation, 'frozen_candidate_run': str(candidate_run), 'pairs': pairs,
               'executed_cases': cases, 'execution_projection': project,
               'candidate_differential_failures': sum(p['candidate'] != 'baseline' and p['differential_failure'] for p in pairs),
               'cases_with_candidate_differential_failure': sorted({p['case'] for p in pairs if p['candidate'] != 'baseline' and p['differential_failure']}),
               'new_model_requests': 0, 'runner_invocations': sum(a['executed'] for a in assessments),
               'new_product_test_runs': sum(a['executed'] and a['named']['status'] == 'named_test_observed' for a in assessments),
               'typechecking_not_measured': True,
               'interpretation': 'controlled-entry local-edit executability; no claim of minimal edits, complete search, or an 88-task success rate'}
    write_json(out/'summary.json', summary)
    print(json.dumps({key: value for key, value in summary.items() if key != 'pairs'}, ensure_ascii=False, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['generate', 'evaluate'])
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--candidate-run', type=Path)
    parser.add_argument('--reason')
    parser.add_argument('--cases', nargs='+', choices=list(ENTRIES))
    parser.add_argument('--project-named-test', action='store_true')
    args = parser.parse_args()
    if args.operation == 'generate':
        generate(args.out.resolve())
    else:
        evaluate(args.out.resolve(), args.candidate_run.resolve() if args.candidate_run else None,
                 args.reason, args.cases, args.project_named_test)


if __name__ == '__main__':
    main()
