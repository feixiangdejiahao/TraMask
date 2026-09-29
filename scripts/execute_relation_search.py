"""Materialize source-owned search candidates with isolated controls.

Reuses the proven language harness and offline replay adapter. Search selection
and semantic assessment are supplied as frozen inputs, not performed here.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import fcntl
import json
import re
import shlex
import shutil
import tomllib
import time
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


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


def go_isolation_harness(emission, items, timeout):
    """Bind exact emitted names to their package, including donor controls."""
    if timeout <= 5:
        raise ValueError('Go isolation requires a phase timeout greater than five seconds')
    packages = defaultdict(list)
    for item in items:
        if item['path'] not in emission['files']:
            raise ValueError('Go selected test has no emitted source file')
        parent = Path(item['path']).parent
        package = './' if parent == Path('.') else './' + str(parent)
        packages[package].append(item['test_name'])
    if not packages:
        raise ValueError('No Go tests selected for isolation')
    packages = {package: list(dict.fromkeys(names)) for package, names in sorted(packages.items())}
    helper = '.relational_phase_inputs/go_test_runner.py'
    command = ('python3 ' + shlex.quote(helper)
               + ''.join(' --package ' + shlex.quote(package) for package in packages)
               + ' --tests ' + shlex.quote(json.dumps(packages))
               + ' --timeout ' + str(timeout - 5)
               + ' --report "$COMBINATION_REPORT_DIR/go.jsonl"')
    return {'command': command, 'report_format': 'go-json', 'report_path': 'go.jsonl',
            'files': {helper: (ROOT/'scripts/relational_go_test_runner.py').read_text()},
            'isolation': {'kind': 'go_test_process', 'selection': packages,
                          'summary_path': 'go.runner.json', 'timeout': timeout - 5}}


def _go_item_view(phase_output, phase, item, summary, digest_cache=None):
    """Normalize one completed process without inheriting sibling failures."""
    from combination_testing.test_reports import parse_report
    parent = Path(item['path']).parent
    package = './' if parent == Path('.') else './' + str(parent)
    name = item['test_name']
    identity = hashlib.sha256(encoded([package, name])).hexdigest()[:24]
    directory = phase_output/'isolated'/identity
    directory.mkdir(parents=True, exist_ok=True)
    summary_path = phase_output/phase['isolation']['summary_path']
    evidence = []
    digest_cache = {} if digest_cache is None else digest_cache

    def record(path):
        if path.is_file():
            key = str(path.resolve())
            if key not in digest_cache:
                with path.open('rb') as stream:
                    digest_cache[key] = hashlib.file_digest(stream, 'sha256').hexdigest()
            row = {'path': key, 'sha256': digest_cache[key]}
            if row not in evidence:
                evidence.append(row)
            return row

    def local_path(value):
        # Sidecar records contain container paths; recover only descendants
        # of its recorded report directory from the copied phase log tree.
        relative = Path(value).relative_to(Path(summary['report']).parent)
        path = (phase_output/relative).resolve()
        if not path.is_relative_to(phase_output.resolve()):
            raise ValueError('Go runtime evidence escapes the phase log directory')
        return path

    record(summary_path)
    record(phase_output/'context.json')
    matches = [row for row in (summary or {}).get('tests', [])
               if row['package'] == package and row['test'] == name]
    row = matches[0] if len(matches) == 1 else None
    process = dict(row.get('process', {})) if row else {}
    status = row['status'] if row else 'missing_isolated_execution'
    result = {**process, 'stage': 'isolated_go_test', 'role': phase['role'],
              'isolation_status': status, 'package': package, 'test_name': name,
              'isolation_reason': row.get('reason') if row else 'No unique recorded execution',
              'phase_output': str(phase_output.resolve()),
              'source_context_file': str((phase_output/'context.json').resolve())}
    raw = b''
    if process.get('stdout'):
        source = local_path(process['stdout'])
        record(source)
        raw = source.read_bytes()
        (directory/'stdout.txt').write_bytes(raw)
        for field, target in [('stderr', 'stderr.txt')]:
            source = local_path(process[field])
            record(source)
            shutil.copyfile(source, directory/target)
        source = local_path(process['stdout']).parent/'process.json'
        record(source)
        if not source.is_file() or load(source) != process:
            raise ValueError('Go sidecar disagrees with its independently recorded process')
        shutil.copyfile(source, directory/'source_process.json')
    else:
        (directory/'stdout.txt').write_bytes(raw)
        (directory/'stderr.txt').write_bytes(b'')
    package_rows = [entry for entry in (summary or {}).get('packages', []) if entry['package'] == package]
    binaries = []
    for entry in package_rows:
        for field in ('discovery', 'compilation'):
            operation = entry.get(field, {})
            for stream in ('stdout', 'stderr'):
                if operation.get(stream):
                    record(local_path(operation[stream]))
            if operation.get('stdout'):
                record(local_path(operation['stdout']).parent/'process.json')
        if entry.get('build_output'):
            record(local_path(entry['build_output']))
        command = entry.get('compilation', {}).get('command', [])
        if '-o' in command:
            binary = record(local_path(command[command.index('-o') + 1]))
            if binary:
                binaries.append(binary)
    if status not in {'pass', 'fail', 'skip'}:
        result['error'] = 'isolated_go_' + status
    if status == 'timeout':
        # Preserve raw stdout, but suppress terminal events from this partial
        # invocation in the derived stream used to judge complete test runs.
        events = []
        for line in raw.decode(errors='replace').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('Action') not in {'pass', 'fail', 'skip'}:
                events.append(event)
        (directory/'go.jsonl').write_text(''.join(json.dumps(event) + '\n' for event in events))
    else:
        (directory/'go.jsonl').write_bytes(raw)
    write(directory/'result.json', result)
    normalized = parse_report(directory, phase['report'], result, selected_names=[item['id']])
    provenance = {'scope': 'one_exact_test_in_one_process', 'package': package, 'test_name': name,
                  'status': status, 'group_summary': str(summary_path.resolve()),
                  'source_context_file': str((phase_output/'context.json').resolve()),
                  'source_snapshot': phase['files'], 'compiled_binaries': binaries,
                  'raw_evidence': evidence,
                  'report_policy': 'omit_terminal_events_for_timeout' if status == 'timeout' else 'exact_test2json_stdout',
                  'derived_report_sha256': hashlib.sha256((directory/'go.jsonl').read_bytes()).hexdigest()}
    write(directory/'provenance.json', provenance)
    normalized['isolation'] = {'status': status, 'provenance': str((directory/'provenance.json').resolve())}
    write(directory/'normalized.json', normalized)
    return directory/'normalized.json', normalized['isolation']


def emit_batch(args):
    from generic_composition.emitter import emit
    from generic_composition.runner import infer_harness
    from relation_search.instrument import instrument_candidates
    from relation_search.checkpoint import start, completed, seal, digest
    frozen(args.input)
    completed(args.input)
    request = dict(stage='emit', input=str(args.input.resolve()), input_sha256=digest(args.input/'prepare.json'),
                   group_size=args.group_size, timeout=args.timeout,
                   algorithm_sha256={name: digest(ROOT/name) for name in (
                       'scripts/execute_relation_search.py', 'scripts/relational_phase_runner.py',
                       'scripts/relational_go_test_runner.py',
                       'relation_search/instrument.py', 'relation_search/runtime.py',
                       'generic_composition/emitter.py', 'generic_composition/runner.py')})
    start(args.output, request)
    existing = completed(args.output)
    if existing is not None:
        return {**existing, 'resumed': True}
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
    candidates = load(args.input/'candidates.json')['candidates']
    for candidate in candidates:
        if not candidate.get('base_test_id') or not candidate.get('source_provenance', candidate.get('provenance', candidate.get('source_evidence'))):
            raise ValueError('Search candidate requires source provenance')
        candidate.setdefault('execution_lane', 'relation_search')
        candidate.setdefault('static_parent_id', candidate['id'])
    lanes = {'version': 'relation_search_execution_v1',
             'source_q_count': sum(not c.get('semantic_revision') for c in candidates),
             'llm_q_count': sum(bool(c.get('semantic_revision')) for c in candidates),
             'source': str(args.input.resolve()),
             'selection': 'frozen program-owned candidate batch',
             'max_group_size': args.group_size}
    write(args.output/'execution_lanes.json', lanes)
    raw = {candidate['id']: candidate for candidate in candidates if not candidate.get('is_source_profile')}
    instrumentation = instrument_candidates(corpus, list(raw.values()))
    write(args.output/'instrumentation.json', instrumentation)
    write(args.output/'raw_candidates.json', list(raw.values()))
    all_instrumented = {row['id']: row for row in instrumentation['candidates']}
    unique = {key: all_instrumented[key] for key in raw}
    write(args.output/'accepted.json', list(all_instrumented.values()))
    helper_files = {row['path']: row['code'] for row in instrumentation['helper_files']}
    groups = defaultdict(list)
    for candidate in unique.values():
        key = (candidate['execution_lane'], corpus['tests'][candidate['base_test_id']]['span']['path'])
        groups[key].append(candidate)
    batches = [(key, members[start:start+args.group_size])
               for key, members in sorted(groups.items())
               for start in range(0, len(members), args.group_size)]
    artifacts = []
    for index, ((lane, path), members) in enumerate(batches):
        emitted = emit(corpus, members)
        source_profile_ids = {key for row in members for key in row.get('source_profile_ids', [])}
        profiles = [all_instrumented[key] for key in sorted(source_profile_ids)]
        profile_emitted = emit(corpus, profiles) if profiles else None
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
        if profile_emitted:
            write(folder/'source_profile_emission.json', profile_emitted)
        def selector(rows):
            if case['language'] == 'python':
                return ' or '.join(row['test_name'] for row in rows)
            if case['language'] == 'go':
                return '^(' + '|'.join(re.escape(row['test_name']) for row in rows) + ')$'
            # JavaScript framework filters use full enclosing-suite titles.
            return '(' + '|'.join(re.escape(row['test_name']) for row in rows) + ')$'
        try:
            if case['language'] == 'go':
                harness = go_isolation_harness(emitted, emitted['obligations'], args.timeout)
                control_harness = go_isolation_harness(control_emitted, control_emitted['controls'], args.timeout)
                profile_harness = (go_isolation_harness(profile_emitted, profile_emitted['obligations'], args.timeout)
                                   if profile_emitted and profile_emitted['obligations'] else None)
            else:
                harness = infer_harness(Path(case['repository']), case['language'], list(emitted['files']),
                                       name_filter=selector(emitted['obligations']))
                control_harness = infer_harness(Path(case['repository']), case['language'], list(control_emitted['files']),
                                               name_filter=selector(emitted['controls']))
                profile_harness = infer_harness(Path(case['repository']), case['language'], list(profile_emitted['files']),
                                                name_filter=selector(profile_emitted['obligations'])) if profile_emitted and profile_emitted['obligations'] else None
        except ValueError as exc:
            write(folder/'unsupported.json', {'error': str(exc)})
            continue
        mounts = []
        python_env = python_source_environment(Path(case['repository'])) if case['language'] == 'python' else {'command': ''}
        phases = []
        phase_inputs = [('control', control_emitted, control_harness)]
        if profile_harness:
            phase_inputs.append(('source_profile', profile_emitted, profile_harness))
        phase_inputs.append(('generated', emitted, harness))
        for role, emission, current_harness in phase_inputs:
            files = {**emission['files'], **current_harness.get('files', {})}
            if role != 'control':
                for helper_path, helper_code in helper_files.items():
                    if helper_path in files and files[helper_path] != helper_code:
                        raise ValueError('Runtime helper conflicts with source test')
                    files[helper_path] = helper_code
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
            phase = {'role': role, 'command': python_env['command'] + current_harness['command'],
                     'timeout': args.timeout, 'files': phase_files,
                     'report': {'format': current_harness['report_format'], 'path': current_harness['report_path']}}
            if current_harness.get('isolation'):
                phase['isolation'] = current_harness['isolation']
            phases.append(phase)
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
                    'profile_obligations': profile_emitted['obligations'] if profile_emitted else [],
                    'source_profile_ids': sorted(source_profile_ids),
                    'timeout': len(phases) * args.timeout + 30, 'original_input': str(args.input.resolve())}
        write(folder/'manifest.json', manifest)
        artifacts.append(str(folder.resolve()))
    write(args.output/'artifacts.json', artifacts)
    result = {'execution_hypotheses': len(unique), 'source_profiles': len(all_instrumented)-len(unique),
              'source_q': lanes['source_q_count'],
              'llm_q': lanes['llm_q_count'], 'artifacts': len(artifacts)}
    seal(args.output, result)
    return result


def run(args):
    from combination_testing.test_reports import parse_report
    from relation_search.checkpoint import start, completed, seal, digest
    from scripts.run_relational_gap_case import run_case
    if not 1 <= args.workers <= 2:
        raise ValueError('Offline replay supports at most two workers')
    completed(args.input)  # Verify a new-style frozen materialization, if present.
    artifacts = load(args.input/'artifacts.json')
    request = dict(stage='run', input=str(args.input.resolve()), workers=args.workers,
                   artifacts_sha256={path: digest(Path(path)/'manifest.json') for path in artifacts},
                   registry_sha256=digest(args.registry), runner_sha256=digest(Path(__file__)))
    start(args.output, request)
    lock = (args.output/'.run.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    existing = completed(args.output)
    if existing is not None:
        lock.close()
        return {**existing, 'resumed': True}

    def worker(path):
        path = Path(path)
        manifest = load(path/'manifest.json')
        for mount in manifest['mounts']:
            if hashlib.sha256(Path(mount['source']).read_bytes()).hexdigest() != mount['sha256']:
                raise ValueError('Frozen emitted file modified')
        destination = args.output/path.name
        # A completed Docker process can be normalized again after interruption.
        # An incomplete attempt is preserved and replayed in a fresh directory.
        attempt = 0
        while destination.exists() and not (destination/'execution.json').exists():
            attempt += 1
            destination = args.output/(path.name + '_attempt_' + str(attempt))
        if (destination/'execution.json').exists():
            result = load(destination/'execution.json')
        else:
            result = run_case(manifest['case'], manifest['command'], mounts=manifest['mounts'],
                              timeout=manifest['timeout'], output=destination, registry=args.registry)
        rows, reports = [], {}
        for phase in manifest['phases']:
            role = phase['role']
            phase_output = destination/role
            phase_result = load(phase_output/'result.json') if (phase_output/'result.json').exists() else {'error': 'phase_not_observed', **result}
            items = (manifest['controls'] if role == 'control' else
                     manifest.get('profile_obligations', []) if role == 'source_profile' else manifest['obligations'])
            isolation_summary = None
            isolated = phase.get('isolation', {}).get('kind') == 'go_test_process'
            if isolated:
                isolation_path = phase_output/phase['isolation']['summary_path']
                isolation_summary = load(isolation_path) if isolation_path.is_file() else None
                if isolation_summary is None or isolation_summary.get('status') == 'error':
                    # Group accounting retains errors. Individual completed
                    # processes below remain usable even when a sibling hangs.
                    phase_result = {**phase_result, 'error': ('go_isolation_summary_missing' if isolation_summary is None
                                                            else 'go_isolation_execution_errors')}
            normalized = parse_report(phase_output, phase['report'], phase_result, selected_names=[x['id'] for x in items])
            if isolated:
                normalized['isolation'] = {'summary': str((phase_output/phase['isolation']['summary_path']).resolve()),
                                           'counts': (isolation_summary or {}).get('counts', {})}
            write(phase_output/'normalized.json', normalized)
            reports[role] = normalized
            isolation_digests = {}
            for item in items:
                report_path, isolation = phase_output/'normalized.json', None
                if isolated:
                    report_path, isolation = _go_item_view(phase_output, phase, item, isolation_summary, isolation_digests)
                rows.append({'case': manifest['case'], 'candidate_id': item.get('candidate_id'),
                         'execution_lane': manifest['execution_lane'],
                         'static_parent_id': manifest['static_parent_ids'].get(item.get('candidate_id')),
                         'base_test_id': item['base_test_id'], 'role': role,
                         'test_ids': [item['id']], 'control_ids': item.get('control_ids', []),
                         'result': str(report_path.resolve()),
                         **({'isolation': isolation} if isolation else {}),
                         'trace': str((phase_output/'relation_trace.jsonl').resolve()),
                         'execution_context': {'phase': role, 'source_snapshot': phase['files'],
                                               'control_context': manifest['control_context'],
                                               'context_file': str((phase_output/'context.json').resolve())},
                         'manifest': str((path/'manifest.json').resolve())})
        counts = {role: report['counts'] for role, report in reports.items()}
        elapsed = sum(load(destination/phase['role']/'result.json').get('elapsed_seconds', 0)
                      for phase in manifest['phases'] if (destination/phase['role']/'result.json').exists())
        return rows, {**reports.get('generated', {'status': 'error', 'counts': {}, 'errors': ['missing_generated_phase']}),
                      'phase_counts': counts, 'elapsed_test_seconds': elapsed, 'output': str(destination)}

    runs, summary = [], []
    started = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(worker, artifact): artifact for artifact in artifacts}
            for future in as_completed(futures):
                artifact = futures[future]
                try:
                    rows, result = future.result()
                    runs.extend(rows)
                    summary.append({'artifact': artifact, 'status': result['status'], 'counts': result['counts'],
                                    'errors': result['errors'], 'phase_counts': result['phase_counts'],
                                    'elapsed_test_seconds': result['elapsed_test_seconds'], 'output': result['output']})
                except Exception as exc:
                    summary.append({'artifact': artifact, 'status': 'error', 'error_type': type(exc).__name__,
                                    'error': str(exc)})
                runs.sort(key=lambda row: (row['manifest'], {'control': 0, 'source_profile': 1, 'generated': 2}[row['role']], row['test_ids']))
                summary.sort(key=lambda row: row['artifact'])
                write(args.output/'runs.json', runs)
                write(args.output/'summary.json', summary)
                print(json.dumps(summary[-1]), flush=True)
        # Empty rounds still have explicit execution records.
        write(args.output/'runs.json', runs)
        write(args.output/'summary.json', summary)
        result = {'artifacts': len(artifacts), 'outcomes': summary,
                  'wall_seconds': round(time.monotonic()-started, 3)}
        seal(args.output, result)
        return result
    finally:
        lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['emit', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--group-size', type=int, default=16)
    parser.add_argument('--registry', type=Path, default=ROOT/'data/relational_gap_v1/registry.json')
    parser.add_argument('--dependency-packages-root', type=Path,
                        default=ROOT/'data/relational_gap_v1_dependency_packages')
    args = parser.parse_args()
    result = {'emit': emit_batch, 'run': run}[args.stage](args)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
