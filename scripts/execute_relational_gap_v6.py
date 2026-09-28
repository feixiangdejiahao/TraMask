"""Source-q hypotheses plus optional model-q revisions, uniformly executed."""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import re
import shlex
import tomllib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relational_gap.provider import dispatch, encoded
from relational_gap.semantics_v2 import prepare_requests, validate_response, SemanticBudget


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def load(path):
    return json.loads(path.read_text())


def frozen(directory):
    manifest = load(directory/'prepare.json')
    for name, sha in manifest['files_sha256'].items():
        if hashlib.sha256((directory/name).read_bytes()).hexdigest() != sha:
            raise ValueError('Frozen input modified: ' + name)
    return manifest


def requests(args):
    frozen(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    corpus = load(args.input/'corpus.json')
    frontend = load(args.input/'frontend.json')
    candidates = load(args.input/'candidates.json')['candidates']
    protocol = {'version': 1, 'input': str(args.input.resolve()), 'model': 'deepseek-v4-flash',
                'semantic_budget': SemanticBudget().__dict__, 'max_output_tokens': 16384,
                'temperature': 0, 'source_program_generated_candidates_only': True,
                'target_labels_reference_or_execution_inputs': False,
                'algorithm_hashes': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                     for p in [*ROOT.glob('relational_gap/*.py'), Path(__file__)]}}
    write(args.output/'protocol.json', protocol)
    result = prepare_requests(corpus, frontend, candidates, (args.input/'issue.md').read_text())
    for req in result.pop('requests'):
        write(args.output/f'request_{req["index"]}.json', req)
    write(args.output/'selection.json', result)
    return {'requests': len(list(args.output.glob('request_*.json'))), 'skipped': len(result['skipped'])}


def complete(args):
    request = load(args.input/f'request_{args.index}.json')
    manifest = dispatch(request, args.output, root=ROOT)
    if manifest['status'] != 'complete':
        return manifest
    protocol = load(args.input/'protocol.json')
    corpus = load(Path(protocol['input'])/'corpus.json')
    validation = validate_response(request, (args.output/'completion.txt').read_text(), corpus=corpus)
    write(args.output/'validation.json', validation)
    return {'status': manifest['status'], 'accepted': len(validation['accepted']),
            'unknown': len(validation['unknown']), 'rejected': len(validation['rejected']),
            'protocol_error': validation.get('protocol_error'), 'usage': manifest.get('usage')}


def python_source_environment(repository):
    """Discover import roots from repository layout and packaging metadata."""
    roots = ["."]
    declarations = []
    config = repository / "pyproject.toml"
    if config.exists():
        try:
            document = tomllib.loads(config.read_text())
            declarations.extend(document.get("tool", {}).get("setuptools", {}).get("package-dir", {}).values())
            declarations.extend(row.get("from") for row in document.get("tool", {}).get("poetry", {}).get("packages", []) if isinstance(row, dict))
        except (ValueError, TypeError):
            pass
    # The conventional src layout is recognized only when present on disk.
    declarations.append("src")
    for value in declarations:
        if not isinstance(value, str):
            continue
        directory = (repository / value).resolve()
        if directory.is_relative_to(repository.resolve()) and directory.is_dir():
            relative = str(directory.relative_to(repository.resolve()))
            if relative not in roots:
                roots.append(relative)
    paths = ["/app" if root == "." else "/app/" + root for root in roots]
    return {"repository_source_roots": roots,
            "command": "export PYTHONPATH=" + shlex.quote(":".join(paths)) + ':"${PYTHONPATH:-}"\n',
            "basis": "repository_root_and_existing_package_source_directories"}


def emit_batch(args):
    from generic_composition.emitter import emit
    from generic_composition.runner import infer_harness
    frozen(args.input)
    args.output.mkdir(parents=True, exist_ok=False)
    case = load(args.input/'case.json')
    corpus = load(args.input/'corpus.json')
    selection = load(args.input/'selection.json')
    package_sources = {}
    if case['language'] == 'go':
        inventory_path = args.dependency_packages_root / (case['id'] + '.json')
        inventory = load(inventory_path)
        if inventory.get('image') != case['image']:
            raise ValueError('Dependency package inventory image mismatch')
        package_sources = inventory['import_package_sources']
        write(args.output/'dependency_package_inventory.json', {
            'path': str(inventory_path.resolve()),
            'sha256': hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
            'image': case['image'], 'package_count': len(package_sources),
            'basis': 'offline exact installed image package source declarations'})
    from scripts.relational_execution_lanes import execution_lanes
    if args.semantics is None:
        raise ValueError('emit requires frozen --semantics offered records')
    protocol = load(args.semantics/'protocol.json')
    if Path(protocol['input']).resolve() != args.input.resolve():
        raise ValueError('Request preparation source mismatch')
    offered_requests = [load(path) for path in sorted(args.semantics.glob('request_*.json'))]
    validations, artifact_errors = [], []
    for result in args.completions:
        try:
            validations.append(load(result/'validation.json'))
        except (OSError, ValueError) as error:
            artifact_errors.append({'path': str(result/'validation.json'),
                                    'error_type': type(error).__name__, 'status': 'source_lane_retained'})
    candidates, lanes = execution_lanes(offered_requests, validations,
                                       load(args.input/'candidates.json')['candidates'])
    lanes['model_artifact_errors'] = artifact_errors
    write(args.output/'execution_lanes.json', lanes)
    unique = {candidate['id']: candidate for candidate in candidates}
    write(args.output/'accepted.json', list(unique.values()))
    groups = defaultdict(list)
    for candidate in unique.values():
        groups[(candidate['execution_lane'], corpus['tests'][candidate['base_test_id']]['span']['path'])].append(candidate)
    artifacts = []
    for index, ((lane, path), members) in enumerate(sorted(groups.items(), key=lambda item: (item[0][0] != "source_q", item[0][1]))):
        emitted = emit(corpus, members)
        folder = args.output/f'group_{index:03d}'
        if case['language'] == 'go':
            from scripts.go_history_dependencies_v6 import recover_go_dependencies
            from scripts.go_dependency_import_aliases import explicit_dependency_imports
            from scripts.go_materialization import materialize_go_files
            emitted['files'], dependency_records = recover_go_dependencies(
                emitted['files'], corpus, selection, Path(case['repository']),
                import_package_sources=package_sources)
            emitted['files'], import_aliases = explicit_dependency_imports(emitted['files'], package_sources)
            emitted['files'], materialization = materialize_go_files(
                emitted['files'], emitted['obligations'], emitted['controls'], corpus, selection,
                repository=Path(case['repository']))
            write(folder/'materialization.json', materialization)
            write(folder/'dependency_recovery.json', dependency_records)
            write(folder/'dependency_import_aliases.json', import_aliases)
        write(folder/'emission.json', emitted)
        if not emitted['obligations']:
            continue
        admitted_ids = {row['candidate_id'] for row in emitted['obligations']}
        # Exact unedited clones of the same source tests form the first phase.
        # Candidate imports and input/expected edits cannot poison its build.
        control_emitted = emit(corpus, [{**candidate, 'edits': [], 'imports': []}
                                      for candidate in members if candidate['id'] in admitted_ids])
        if {row['id'] for row in control_emitted['controls']} != {row['id'] for row in emitted['controls']}:
            raise ValueError('Control-only emission changed source-control identity')
        if case['language'] == 'go':
            control_emitted['files'], control_dependencies = recover_go_dependencies(
                control_emitted['files'], corpus, selection, Path(case['repository']),
                import_package_sources=package_sources)
            control_emitted['files'], control_aliases = explicit_dependency_imports(control_emitted['files'], package_sources)
            control_emitted['files'], control_materialization = materialize_go_files(
                control_emitted['files'], [], control_emitted['controls'], corpus, selection,
                repository=Path(case['repository']))
            write(folder/'control_materialization.json', control_materialization)
            write(folder/'control_dependency_recovery.json', control_dependencies)
            write(folder/'control_dependency_import_aliases.json', control_aliases)
        write(folder/'control_emission.json', control_emitted)
        def selector(rows):
            if case['language'] == 'python':
                return ' or '.join(row['test_name'] for row in rows)
            if case['language'] == 'go':
                return '^(' + '|'.join(re.escape(row['test_name']) for row in rows) + ')$'
            # JavaScript framework filters use full enclosing-suite titles.
            return '(' + '|'.join(re.escape(row['test_name']) for row in rows) + ')$'
        try:
            harness = infer_harness(Path(case['repository']), case['language'], list(emitted['files']),
                                    name_filter=selector(emitted['obligations']))
            control_harness = infer_harness(Path(case['repository']), case['language'], list(control_emitted['files']),
                                           name_filter=selector(emitted['controls']))
        except ValueError as exc:
            write(folder/'unsupported.json', {'error': str(exc)})
            continue
        mounts = []
        python_env = python_source_environment(Path(case['repository'])) if case['language'] == 'python' else {'command': ''}
        phases = []
        for role, emission, current_harness in [('control', control_emitted, control_harness), ('generated', emitted, harness)]:
            files = {**emission['files'], **current_harness.get('files', {})}
            phase_files = []
            for name, code in files.items():
                destination = folder/role/'files'/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(code)
                digest = hashlib.sha256(destination.read_bytes()).hexdigest()
                # Test discovery (notably Vitest path filters) can include a
                # hidden directory. Snapshot names must not look like tests.
                staged = '.relational_phase_inputs/' + role + '/' + hashlib.sha256(name.encode()).hexdigest() + '.snapshot'
                mounts.append({'source': str(destination.resolve()), 'target': staged, 'sha256': digest})
                phase_files.append({'target': name, 'staged': staged, 'sha256': digest})
            phases.append({'role': role, 'command': python_env['command'] + current_harness['command'],
                           'timeout': args.timeout, 'files': phase_files,
                           'report': {'format': current_harness['report_format'], 'path': current_harness['report_path']}})
        plan_path = folder/'phase_plan.json'
        write(plan_path, {'phases': phases})
        runner_path = folder/'phase_runner.py'
        runner_path.write_bytes((ROOT/'scripts/relational_phase_runner.py').read_bytes())
        for source, target in [(plan_path, '.relational_phase_inputs/plan.json'),
                               (runner_path, '.relational_phase_inputs/runner.py')]:
            mounts.append({'source': str(source.resolve()), 'target': target,
                           'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        manifest = {'case': case['id'], 'execution_lane': lane,
                    'static_parent_ids': {c['id']: c['static_parent_id'] for c in members},
                    'candidate_ids': [c['id'] for c in members],
                    'command': 'python3 .relational_phase_inputs/runner.py .relational_phase_inputs/plan.json',
                    'source_environment': python_env,
                    'phases': phases, 'control_context': 'separate_source_control_snapshot_with_recorded_binding_materialization',
                    'mounts': mounts, 'obligations': emitted['obligations'], 'controls': emitted['controls'],
                    'timeout': 2 * args.timeout + 30, 'original_input': str(args.input.resolve())}
        write(folder/'manifest.json', manifest)
        artifacts.append(str(folder.resolve()))
    write(args.output/'artifacts.json', artifacts)
    return {'execution_hypotheses': len(unique), 'source_q': lanes['source_q_count'],
            'llm_q': lanes['llm_q_count'], 'artifacts': len(artifacts)}


def run(args):
    from combination_testing.test_reports import parse_report
    from scripts.run_relational_gap_case import run_case
    args.output.mkdir(parents=True, exist_ok=False)
    artifacts = load(args.input/'artifacts.json')
    def worker(path):
        path = Path(path)
        manifest = load(path/'manifest.json')
        for mount in manifest['mounts']:
            if hashlib.sha256(Path(mount['source']).read_bytes()).hexdigest() != mount['sha256']:
                raise ValueError('Frozen emitted file modified')
        destination = args.output/path.name
        result = run_case(manifest['case'], manifest['command'], mounts=manifest['mounts'],
                          timeout=manifest['timeout'], output=destination, registry=args.registry)
        rows = []
        reports = {}
        for phase in manifest['phases']:
            role = phase['role']
            phase_output = destination/role
            phase_result = load(phase_output/'result.json') if (phase_output/'result.json').exists() else {'error': 'phase_not_observed', **result}
            items = manifest['controls'] if role == 'control' else manifest['obligations']
            normalized = parse_report(phase_output, phase['report'], phase_result, selected_names=[x['id'] for x in items])
            write(phase_output/'normalized.json', normalized)
            reports[role] = normalized
            for item in items:
                rows.append({'case': manifest['case'], 'candidate_id': item.get('candidate_id'),
                         'execution_lane': manifest['execution_lane'],
                         'static_parent_id': manifest['static_parent_ids'].get(item.get('candidate_id')),
                         'base_test_id': item['base_test_id'], 'role': 'control' if item['is_control'] else 'generated',
                         'test_ids': [item['id']], 'control_ids': item.get('control_ids', []),
                         'result': str((phase_output/'normalized.json').resolve()),
                         'execution_context': {'phase': role, 'source_snapshot': phase['files'],
                                               'control_context': manifest['control_context'],
                                               'context_file': str((phase_output/'context.json').resolve())},
                         'manifest': str((path/'manifest.json').resolve())})
        return rows, {**reports['generated'], 'control_phase': reports['control']}
    runs, summary = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, artifact): artifact for artifact in artifacts}
        for future in as_completed(futures):
            artifact = futures[future]
            try:
                rows, result = future.result()
                runs.extend(rows)
                summary.append({'artifact': artifact, 'status': result['status'], 'counts': result['counts'], 'errors': result['errors']})
            except Exception as exc:
                summary.append({'artifact': artifact, 'status': 'error', 'error_type': type(exc).__name__})
            write(args.output/'runs.json', runs)
            write(args.output/'summary.json', summary)
            print(json.dumps(summary[-1]), flush=True)
    return {'artifacts': len(artifacts), 'outcomes': summary}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['requests', 'complete', 'emit', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--index', type=int, default=0)
    parser.add_argument('--semantics', type=Path)
    parser.add_argument('--completions', type=Path, nargs='*', default=[])
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    parser.add_argument('--dependency-packages-root', type=Path,
                        default=ROOT/'data/relational_gap_v1_dependency_packages')
    args = parser.parse_args()
    result = {'requests': requests, 'complete': complete, 'emit': emit_batch, 'run': run}[args.stage](args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
