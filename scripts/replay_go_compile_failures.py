"""Plan and replay unchanged Go candidates blocked by a shared compile error.

This supplement never changes the source campaign or invokes a model. Planning
is read-only; execution uses fresh candidate compilation snapshots and controls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor_retrieval.syntax import Source, child, walk
from relation_search.checkpoint import completed, digest, read, seal, start, write
from scripts.execute_relation_search import emit_batch, run

POLICY = 'unchanged-go-shared-compile-failure-replay-v1'


def value_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def code_identity():
    return {name: digest(ROOT/name) for name in (
        'scripts/replay_go_compile_failures.py', 'scripts/execute_relation_search.py',
        'scripts/relational_go_test_runner.py', 'scripts/relational_phase_runner.py',
        'scripts/run_relational_gap_case.py', 'vendor/replay/container_replay.py',
        'scripts/go_history_dependencies_v6.py', 'scripts/go_dependency_import_aliases.py',
        'scripts/go_materialization.py', 'scripts/go_source_materializer/main.go',
        'generic_composition/emitter.py', 'generic_composition/runner.py',
        'relation_search/instrument.py', 'relation_search/checkpoint.py',
        'anchor_retrieval/syntax.py', 'combination_testing/test_reports.py')}


def checked(path, files, expected=None):
    path = Path(path).resolve()
    checksum = digest(path)
    if expected is not None and checksum != expected:
        raise ValueError('Frozen source changed: '+str(path))
    files[str(path)] = checksum
    return path


def sealed_file(directory, path, files):
    directory, path = Path(directory).resolve(), Path(path).resolve()
    checkpoint = checked(directory/'checkpoint.json', files)
    relative = str(path.relative_to(directory))
    checksum = read(checkpoint)['files_sha256'].get(relative)
    if checksum is None:
        raise ValueError('Source file absent from completed checkpoint: '+str(path))
    return checked(path, files, checksum)


def test_body(emission, item):
    source = Source(item['path'], emission['files'][item['path']], 'go')
    nodes = [node for node in walk(source.root) if node.type in {'function_declaration', 'method_declaration'}
             and source.text(child(node, 'name')) == item['test_name']]
    if len(nodes) != 1:
        raise ValueError('No unique emitted Go test body: '+item['test_name'])
    return hashlib.sha256(source.text(nodes[0]).encode()).hexdigest()


def plan(campaign, registry, dependency_packages_root):
    campaign, registry = Path(campaign).resolve(), Path(registry).resolve()
    registry_sha = digest(registry)
    records = {row['id']: row for row in read(registry)}
    groups, skipped = [], []
    # Completion is a round's sealed runs index, independent of whether another
    # case/round is still running. Only used evidence is read and SHA checked.
    for index in sorted(campaign.glob('*/round_*/executed/runs.json')):
        execution = index.parent
        if not (execution/'checkpoint.json').is_file():
            skipped.append(dict(path=str(index), reason='execution_not_sealed'))
            continue
        common = {}
        sealed_file(execution, index, common)
        stage = read(sealed_file(execution, execution/'stage.json', common))
        manifests = sorted({row['manifest'] for row in read(index) if row['role'] == 'generated'})
        for manifest_path in manifests:
            files = dict(common)
            manifest_path = Path(manifest_path).resolve()
            emitted = manifest_path.parent.parent
            manifest = read(sealed_file(emitted, manifest_path, files))
            if len(manifest['candidate_ids']) < 2:
                continue
            generated = [row for row in manifest['phases'] if row['role'] == 'generated']
            if len(generated) != 1 or generated[0].get('isolation', {}).get('kind') != 'go_test_process':
                continue
            relevant = [row for row in read(index) if row['role'] == 'generated'
                        and Path(row['manifest']).resolve() == manifest_path]
            directories = {Path(row['execution_context']['context_file']).parent.resolve() for row in relevant}
            if len(directories) != 1:
                raise ValueError('One group must have one generated phase context')
            phase = next(iter(directories))
            summary_path = phase/generated[0]['isolation']['summary_path']
            summary = read(sealed_file(execution, summary_path, files))
            failures = [row for row in summary['packages'] if row['status'] == 'compile_error']
            if not failures:
                continue
            if stage['registry_sha256'] != registry_sha:
                raise ValueError('Replay registry differs from original run: '+str(registry))
            checked(registry, files, registry_sha)
            source = Path(manifest['original_input']).resolve()
            prepare = read(checked(source/'prepare.json', files))
            for name in ('case.json', 'corpus.json', 'selection.json'):
                checked(source/name, files, prepare['files_sha256'][name])
            case = read(source/'case.json')
            if case['language'] != 'go':
                raise ValueError('Go execution manifest has a non-Go corpus')
            record = records[case['id']]
            patch = checked(record['candidate_patch'], files)
            # The transport manifest binds the original run to exact patch and
            # image settings, rather than trusting a currently edited registry.
            transport = read(sealed_file(execution, phase.parent/'manifest.json', files))
            if (transport['candidate_patch_sha256'] != digest(patch)
                    or transport['image'] != record['image']
                    or transport.get('image_id') != record.get('image_id')
                    or transport['expected_base_commit'] != record['base_commit']):
                raise ValueError('Original replay program identity differs from registry')
            inventory = Path(dependency_packages_root).resolve()/(case['id']+'.json')
            dependency = read(sealed_file(emitted, emitted/'dependency_package_inventory.json', files))
            checked(inventory, files, dependency['sha256'])
            raw_path = sealed_file(emitted, emitted/'raw_candidates.json', files)
            pool = {row['id']: row for row in read(raw_path)}
            candidates = [pool[key] for key in manifest['candidate_ids']]
            emission = read(sealed_file(emitted, manifest_path.parent/'emission.json', files))
            controls = read(sealed_file(emitted, manifest_path.parent/'control_emission.json', files))
            emit_stage = read(sealed_file(emitted, emitted/'stage.json', files))
            phase_cost = {}
            for original_phase in manifest['phases']:
                receipt = read(sealed_file(execution, phase.parent/original_phase['role']/'result.json', files))
                phase_cost[original_phase['role']] = receipt.get('elapsed_seconds', 0)
            groups.append(dict(id=value_sha(str(manifest_path))[:24], case=case['id'],
                origin_manifest=str(manifest_path), original_execution=str(execution),
                original_generated_summary=str(summary_path), source=str(source), raw_candidates=str(raw_path),
                candidate_ids=manifest['candidate_ids'], candidate_sha256={row['id']: value_sha(row) for row in candidates},
                original_test_bodies={row['candidate_id']: test_body(emission, row) for row in emission['obligations']},
                original_control_bodies={row['id']: test_body(controls, row) for row in controls['controls']},
                compile_error_packages=[row['package'] for row in failures],
                settings=dict(timeout=emit_stage['timeout'], group_size=emit_stage['group_size'],
                              workers=stage['workers']), original_phase_seconds=phase_cost, files_sha256=files))
    return dict(policy=POLICY, campaign=str(campaign), registry=str(registry),
                dependency_packages_root=str(Path(dependency_packages_root).resolve()),
                algorithm_sha256=code_identity(), groups=groups, skipped=skipped,
                selection='all sealed multi-candidate Go groups with generated package compile_error',
                cost_estimate=dict(
                    observed_original_phase_seconds=sum(sum(row['original_phase_seconds'].values()) for row in groups),
                    repeat_original_group_phases_per_candidate_seconds=sum(len(row['candidate_ids'])*sum(row['original_phase_seconds'].values()) for row in groups),
                    all_candidate_phase_timeout_seconds=sum(len(row['candidate_ids'])*len(row['original_phase_seconds'])*row['settings']['timeout'] for row in groups),
                    limitation='Repeated original group phase cost is a baseline, not an upper bound: successful new tests and Docker startup add unmeasured cost'),
                provider_calls=0, candidates=sum(len(row['candidate_ids']) for row in groups))


def _prepare(entry, output):
    source = Path(entry['source'])
    pool = {row['id']: row for row in read(Path(entry['raw_candidates']))}
    candidates = [pool[key] for key in entry['candidate_ids']]
    if {row['id']: value_sha(row) for row in candidates} != entry['candidate_sha256']:
        raise ValueError('Candidate content changed')
    output.mkdir(parents=True, exist_ok=True)
    for name in ('case.json', 'corpus.json', 'selection.json'):
        if (output/name).exists():
            if digest(output/name) != digest(source/name):
                raise ValueError('Supplement preparation changed: '+name)
        else:
            shutil.copyfile(source/name, output/name)
    document = dict(candidates=candidates)
    if (output/'candidates.json').exists() and read(output/'candidates.json') != document:
        raise ValueError('Supplement candidates changed')
    write(output/'candidates.json', document)
    write(output/'prepare.json', dict(status='prepared', supplement=POLICY,
        original_manifest=entry['origin_manifest'],
        files_sha256={name: digest(output/name) for name in ('case.json', 'corpus.json', 'selection.json', 'candidates.json')}))
    return output


def _check_emitted_bodies(entry, emitted):
    seen = set()
    for name in read(emitted/'artifacts.json'):
        folder = Path(name)
        manifest = read(folder/'manifest.json')
        if len(manifest['candidate_ids']) != 1:
            raise ValueError('Supplement failed to isolate candidates')
        emission, controls = read(folder/'emission.json'), read(folder/'control_emission.json')
        for item in emission['obligations']:
            if test_body(emission, item) != entry['original_test_bodies'][item['candidate_id']]:
                raise ValueError('Re-emission changed a candidate test body')
            seen.add(item['candidate_id'])
        for item in controls['controls']:
            if test_body(controls, item) != entry['original_control_bodies'][item['id']]:
                raise ValueError('Re-emission changed an original control')
    if seen != set(entry['original_test_bodies']):
        raise ValueError('Re-emission lost a candidate')


def execute(plan_path, output, workers=None):
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    frozen = read(plan_path)
    if frozen['policy'] != POLICY or frozen['algorithm_sha256'] != code_identity():
        raise ValueError('Supplement algorithm changed; create a new plan')
    if output.is_relative_to(Path(frozen['campaign'])):
        raise ValueError('Supplement output must be outside the original campaign')
    for entry in frozen['groups']:
        for path, checksum in entry['files_sha256'].items():
            checked(path, {}, checksum)
    request = dict(stage=POLICY, plan=str(plan_path), plan_sha256=digest(plan_path), workers=workers)
    start(output, request)
    prior = completed(output)
    if prior is not None:
        return {**prior, 'resumed': True}
    summaries = []
    for entry in frozen['groups']:
        folder = output/entry['id']
        prepared = _prepare(entry, folder/'prepared')
        emitted, executed = folder/'emitted', folder/'executed'
        emit_batch(SimpleNamespace(input=prepared, output=emitted,
            dependency_packages_root=Path(frozen['dependency_packages_root']),
            group_size=entry['settings']['group_size'], timeout=entry['settings']['timeout'],
            isolate_go_compilation=True))
        _check_emitted_bodies(entry, emitted)
        result = run(SimpleNamespace(input=emitted, output=executed, registry=Path(frozen['registry']),
                                    workers=workers or entry['settings']['workers']))
        rows = read(executed/'runs.json')
        phases = [read(path) for path in sorted(executed.glob('group_*/*/go.runner.json'))]
        compilations = [package['compilation'] for phase in phases for package in phase['packages']
                        if package.get('compilation')]
        statuses = {}
        for row in rows:
            if row['role'] == 'generated':
                statuses[row['candidate_id']] = dict(status=read(Path(row['result']))['status'],
                    isolation=row.get('isolation', {}).get('status'), result=row['result'])
        summary = dict(id=entry['id'], original_manifest=entry['origin_manifest'],
            original_generated_summary=entry['original_generated_summary'],
            candidate_statuses=statuses, candidate_ids=entry['candidate_ids'],
            controls=[dict(result=row['result'], status=read(Path(row['result']))['status'])
                      for row in rows if row['role'] == 'control'],
            replay_invocations=result['artifacts'], compile_commands=len(compilations),
            compilation_seconds=sum(row['elapsed_seconds'] for row in compilations),
            wall_seconds=result['wall_seconds'], executed_index=str(executed/'runs.json'))
        write(folder/'supplement.json', summary)
        summaries.append(summary)
        write(output/'summary.json', summaries)
    result = dict(groups=len(summaries), candidates=frozen['candidates'], provider_calls=0,
                  replay_invocations=sum(row['replay_invocations'] for row in summaries),
                  compile_commands=sum(row['compile_commands'] for row in summaries),
                  wall_seconds=sum(row['wall_seconds'] for row in summaries))
    seal(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    planning = commands.add_parser('plan')
    planning.add_argument('--campaign', type=Path, required=True)
    planning.add_argument('--registry', type=Path, required=True)
    planning.add_argument('--dependency-packages-root', type=Path,
                          default=ROOT/'data/relational_gap_v1_dependency_packages')
    planning.add_argument('--output', type=Path, required=True)
    replay = commands.add_parser('execute')
    replay.add_argument('--plan', type=Path, required=True)
    replay.add_argument('--output', type=Path, required=True)
    replay.add_argument('--workers', type=int, choices=[1, 2])
    args = parser.parse_args()
    if args.command == 'plan':
        if args.output.resolve().is_relative_to(args.campaign.resolve()):
            raise ValueError('Plan output must be outside the original campaign')
        result = plan(args.campaign, args.registry, args.dependency_packages_root)
        if args.output.exists() and read(args.output) != result:
            raise ValueError('Refusing to replace a different plan')
        write(args.output, result)
        print(json.dumps(dict(groups=len(result['groups']), candidates=result['candidates'], plan=str(args.output))))
    else:
        print(json.dumps(execute(args.plan, args.output, args.workers)))


if __name__ == '__main__':
    main()
