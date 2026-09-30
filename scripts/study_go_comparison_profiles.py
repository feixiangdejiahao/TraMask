"""Prepare isolated native comparison profiles using source-selected inputs.

One closed integer input edit is the uniform eligibility rule. All 17 trials
remain in the report; unsupported languages and empty pools are explicit.
Profiles describe executed predicates and never generate expected assertions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, child
from relation_search.checkpoint import digest, read, write, seal

VERSION = 'native-go-comparison-profile-study-v1'


def closed_integer(text):
    if not isinstance(text, str) or not text.strip():
        return False
    source = Source('literal.go', 'package p\nvar a = ' + text + '\n', 'go')
    if source.root.has_error or len(source.root.named_children) != 2:
        return False
    declaration = source.root.named_children[-1]
    if declaration.type != 'var_declaration' or len(declaration.named_children) != 1:
        return False
    value = child(declaration.named_children[0], 'value')
    if value is None or len(value.named_children) != 1:
        return False
    if source.text(value) != text.strip():
        return False
    node = value.named_children[0]
    if node.type == 'unary_expression':
        if source.text(child(node, 'operator')) not in {'+', '-'}:
            return False
        node = child(node, 'operand')
    return node is not None and node.type == 'int_literal'


def select_candidates(corpus, candidates, limit=128):
    if limit < 1:
        raise ValueError('positive_candidate_limit_required')
    if corpus['language'] != 'go':
        return dict(status='unsupported_language', eligible_count=0, selected=[], unselected=[])
    eligible = []
    for candidate in candidates:
        edits = candidate.get('edits', [])
        if candidate.get('imports') or len(edits) != 1:
            continue
        edit = edits[0]
        if edit.get('role') != 'input' or not all(closed_integer(edit.get(k)) for k in ('before', 'after')):
            continue
        if edit['before'] == edit['after']:
            continue
        extent = edit.get('span', {})
        source = corpus['sources'].get(extent.get('path'))
        test = corpus['tests'].get(candidate.get('base_test_id'))
        if not source or not test or extent.get('path') != test['span']['path']:
            continue
        start, end = extent.get('start_byte'), extent.get('end_byte')
        span = test['span']
        if (not isinstance(start, int) or not isinstance(end, int)
                or not span['start_byte'] <= start < end <= span['end_byte']
                or source['code'].encode()[start:end] != edit['before'].encode()):
            continue
        eligible.append(candidate)
    if len({row['id'] for row in eligible}) != len(eligible):
        raise ValueError('duplicate_eligible_candidate_id')
    eligible.sort(key=lambda row: (hashlib.sha256(str(row['id']).encode()).hexdigest(), str(row['id'])))
    return dict(status='selected' if eligible else 'no_eligible_integer_input_edit',
                eligible_count=len(eligible), selected=eligible[:limit],
                unselected=[row['id'] for row in eligible[limit:]])


def probe_files(instrumentation):
    """Mount changed production files only; never overwrite emitted tests."""
    paths = {row['original_span']['path'] for row in instrumentation['comparisons']}
    return {**{path: instrumentation['files'][path] for path in sorted(paths)},
            **instrumentation['runtime_files']}


def _materialize(emission, corpus, selection, repository, package_sources):
    from scripts.go_history_dependencies_v6 import recover_go_dependencies
    from scripts.go_dependency_import_aliases import explicit_dependency_imports
    from scripts.go_materialization import materialize_go_files
    files, dependencies = recover_go_dependencies(emission['files'], corpus, selection, repository,
        import_package_sources=package_sources)
    files, aliases = explicit_dependency_imports(files, package_sources)
    files, materialization = materialize_go_files(files, emission['obligations'], emission['controls'],
        corpus, selection, repository=repository)
    return {**emission, 'files': files}, dict(dependencies=dependencies, aliases=aliases, materialization=materialization)


def _artifact(folder, case, candidate, corpus, selection, instrumentation, packages, timeout):
    from generic_composition.emitter import emit
    from scripts.execute_relation_search import go_isolation_harness
    original = emit(corpus, [dict(candidate, edits=[], imports=[])])
    generated = emit(corpus, [candidate])
    write(folder / 'source_emission.json', original)
    write(folder / 'generated_emission.json', generated)
    if len(generated['obligations']) != 1 or generated['unsupported'] or original['unsupported']:
        return dict(status='materialization_unsupported', reasons=generated['unsupported'] + original['unsupported'])
    control_ids = {row['id'] for row in original['controls']}
    if control_ids != {row['id'] for row in generated['controls']}:
        raise ValueError('source_control_identity_changed')
    original, original_report = _materialize(original, corpus, selection, Path(case['repository']), packages)
    generated, generated_report = _materialize(generated, corpus, selection, Path(case['repository']), packages)
    write(folder / 'source_materialization.json', original_report)
    write(folder / 'generated_materialization.json', generated_report)
    write(folder / 'source_materialized_emission.json', original)
    write(folder / 'generated_materialized_emission.json', generated)
    base_controls = [row for row in original['controls'] if row['base_test_id'] == candidate['base_test_id']]
    if len(base_controls) != 1:
        raise ValueError('base_control_not_unique')
    changed = probe_files(instrumentation)
    if set(changed) & (set(original['files']) | set(generated['files'])):
        raise ValueError('probe_overwrites_emitted_test_source')
    phases, mounts = [], []
    for role, emission, items, probes in [
            ('control', original, original['controls'], {}),
            ('source_profile', original, base_controls, changed),
            ('generated', generated, generated['obligations'], changed)]:
        harness = go_isolation_harness(emission, items, timeout)
        files = {**emission['files'], **harness['files'], **probes}
        phase_files = []
        for path, code in sorted(files.items()):
            relative = Path(path)
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe_artifact_path')
            target = folder / role / 'files' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code)
            staged = '.comparison_profile_inputs/' + role + '/' + hashlib.sha256(path.encode()).hexdigest() + '.snapshot'
            mounts.append(dict(source=str(target.resolve()), target=staged, sha256=digest(target)))
            phase_files.append(dict(target=path, staged=staged, sha256=digest(target)))
        command = 'export ' + instrumentation['trace_env'] + '="$COMBINATION_REPORT_DIR/comparison_trace.jsonl"\n' + harness['command']
        phases.append(dict(role=role, command=command, timeout=timeout, files=phase_files,
                           report=dict(format=harness['report_format'], path=harness['report_path']),
                           isolation=harness['isolation']))
    write(folder / 'phase_plan.json', dict(phases=phases))
    helper = folder / 'phase_runner.py'
    helper.write_bytes((ROOT / 'scripts/relational_phase_runner.py').read_bytes())
    for source, target in [(folder / 'phase_plan.json', '.comparison_profile_inputs/plan.json'),
                           (helper, '.comparison_profile_inputs/runner.py')]:
        mounts.append(dict(source=str(source.resolve()), target=target, sha256=digest(source)))
    manifest = dict(case=case['id'], candidate_id=candidate['id'], base_test_id=candidate['base_test_id'],
        command='python3 .comparison_profile_inputs/runner.py .comparison_profile_inputs/plan.json',
        mounts=mounts, phases=phases, controls=original['controls'], base_controls=base_controls,
        obligations=generated['obligations'], timeout=3 * timeout + 30,
        profile_scope='one exact unchanged base test versus one exact input-edited test; independent processes',
        oracle='all inherited assertions unchanged; runtime relations are selection evidence only')
    write(folder / 'manifest.json', manifest)
    return dict(status='prepared', candidate_id=candidate['id'], manifest=str((folder / 'manifest.json').resolve()))


def prepare(paired, census, output, dependency_root, *, limit=128, timeout=90):
    paired, census, output, dependency_root = map(lambda p: Path(p).resolve(), (paired, census, output, dependency_root))
    if output.exists():
        raise ValueError('study_output_already_exists')
    if not 5 < timeout <= 120 or not 0 < limit <= 128:
        raise ValueError('study_budget_outside_fixed_maximum')
    parent = read(paired / 'protocol.json')
    if digest(paired / 'protocol.json') != read(paired / 'ready.json')['protocol_sha256']:
        raise ValueError('source_parent_changed')
    frozen = read(census / 'seal.json')['files_sha256']
    for name, sha in frozen.items():
        if digest(census / name) != sha:
            raise ValueError('source_census_changed')
    if parent['cases'] != read(census / 'protocol.json')['cases'] or len(parent['cases']) != 17:
        raise ValueError('trial_denominator_changed')
    inventory = Path(parent['inventory'])
    selections, records, inputs = {}, {}, {}
    for case_id in parent['cases']:
        directory = inventory / case_id
        for name in ['corpus.json', 'case.json', 'source_pool.json']:
            path = directory / name
            if digest(path) != parent['input_sha256'][case_id][name]:
                raise ValueError('source_input_changed')
            inputs[str(path)] = digest(path)
        corpus = read(directory / 'corpus.json')
        pool = read(directory / 'source_pool.json')
        candidates = pool['candidates'] if isinstance(pool, dict) else pool
        selection = select_candidates(corpus, candidates, limit)
        instrumentation = read(census / case_id / 'instrumentation.json')
        if selection['selected'] and not instrumentation['comparisons']:
            selection['status'] = 'no_supported_modified_function_comparison'
        selections[case_id] = selection
        records[case_id] = dict(status=selection['status'], eligible_count=selection['eligible_count'],
            selected_ids=[row['id'] for row in selection['selected']], unselected_ids=selection['unselected'],
            supported_comparisons=len(instrumentation['comparisons']))
        if selection['selected'] and instrumentation['comparisons']:
            for path in [directory / 'selection.json', dependency_root / (case_id + '.json')]:
                inputs[str(path)] = digest(path)
    names = ['scripts/study_go_comparison_profiles.py', 'scripts/run_relational_gap_case.py',
        'scripts/relational_phase_runner.py', 'scripts/relational_go_test_runner.py',
        'scripts/execute_relation_search.py', 'scripts/go_history_dependencies_v6.py',
        'scripts/go_dependency_import_aliases.py', 'scripts/go_materialization.py',
        'generic_composition/emitter.py', 'anchor_retrieval/syntax.py',
        'experimental/go_comparison_probe.py', 'tests/test_go_comparison_profiles_study.py']
    code = {name: digest(ROOT / name) for name in names}
    output.mkdir(parents=True)
    write(output / 'protocol.json', dict(version=VERSION, cases=parent['cases'], selection=records,
        rule='one exact closed integer input-literal edit, unchanged imports/assertions; SHA256(id) order, uniform limit',
        candidate_limit=limit, phase_timeout=timeout, provider_calls=0, subject_executions=0,
        source_inventory=str(inventory), source_census=str(census), census_seal_sha256=digest(census / 'seal.json'),
        input_sha256=inputs, code_sha256=code, retries=0, replacements=0,
        forbidden=['target labels', 'hidden tests', 'reference patches', 'historical oracle answers'],
        interpretation='native predicate-profile feasibility study, not correct oracles or 17-trial detection'))
    for name in code:
        target = output / 'code_snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    results = {}
    for case_id, selected in selections.items():
        write(output / case_id / 'selection.json', selected)
        results[case_id] = []
        if not selected['selected'] or records[case_id]['status'] != 'selected':
            continue
        directory = inventory / case_id
        corpus, case, selection = (read(directory / name) for name in ['corpus.json', 'case.json', 'selection.json'])
        packages = read(dependency_root / (case_id + '.json'))
        if packages['image'] != case['image']:
            raise ValueError('dependency_inventory_image_changed')
        instrumentation = read(census / case_id / 'instrumentation.json')
        for index, candidate in enumerate(selected['selected']):
            row = _artifact(output / case_id / f'group_{index:03d}', case, candidate, corpus, selection,
                            instrumentation, packages['import_package_sources'], timeout)
            results[case_id].append(row)
            print(json.dumps(dict(case=case_id, **row)), flush=True)
    write(output / 'artifacts.json', results)
    if code != {name: digest(ROOT / name) for name in names} or any(digest(path) != sha for path, sha in inputs.items()):
        raise ValueError('preparation_code_or_input_changed')
    seal(output, dict(trials=17, prepared_artifacts=sum(row['status'] == 'prepared' for rows in results.values() for row in rows),
                      provider_calls=0, subject_executions=0))
    return dict(trials=17, artifacts=sum(len(rows) for rows in results.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired', type=Path, required=True)
    parser.add_argument('--census', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependency-root', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=128)
    parser.add_argument('--timeout', type=int, default=90)
    args = parser.parse_args()
    print(json.dumps(prepare(args.paired, args.census, args.output, args.dependency_root,
                             limit=args.limit, timeout=args.timeout)), flush=True)


if __name__ == '__main__':
    main()
