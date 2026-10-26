"""Freeze and inspect uniformly selected patch-overlap Go comparisons.

This census rewrites source into a separate output tree. It neither executes
that source nor ranks candidates, judges expectations, or reads target labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor_retrieval.syntax import Source, is_test_path, units
from prototypes.patch_observation_priority import _patch_facts


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=True, indent=2) + '\n')


def select_functions(corpus, patch):
    """Select all supported production definitions with verified new patch lines.

    No trial identifier, issue text, candidate result or test target determines
    selection. Unsupported files/functions remain explicitly counted unknown.
    """
    sources, unknowns = [], []
    if corpus['language'] != 'go':
        return sources, [], [dict(reason='language_not_supported', language=corpus['language'])]
    for path, metadata in sorted(corpus['sources'].items()):
        if metadata.get('language', corpus['language']) != 'go':
            continue
        if metadata.get('origin', 'repository') != 'repository':
            continue
        if not metadata.get('complete_file', True) or metadata.get('parse_error'):
            unknowns.append(dict(path=path, reason='incomplete_or_failed_source_parse'))
            continue
        source = Source(path, metadata['code'], 'go')
        if source.root.has_error:
            unknowns.append(dict(path=path, reason='source_parse_error'))
            continue
        sources.append(source)
    lines, _, patch_unknowns = _patch_facts({source.path: source for source in sources}, patch)
    selected = []
    for source in sources:
        if is_test_path(source.path):
            continue
        found, _ = units(source)
        for unit in found:
            if unit.test or unit.node.type not in {'function_declaration', 'method_declaration'}:
                continue
            first, last = unit.node.start_point.row + 1, unit.node.end_point.row + 1
            overlaps = sorted(number for number in lines.get(source.path, ()) if first <= number <= last)
            if overlaps:
                selected.append(dict(path=source.path, start_byte=unit.node.start_byte,
                                     end_byte=unit.node.end_byte, line=first, end_line=last,
                                     verified_patch_lines=overlaps))
    return sources, selected, [*unknowns, *patch_unknowns]


def _safe_path(value):
    path = Path(value)
    if path.is_absolute() or '..' in path.parts or not path.parts:
        raise ValueError('unsafe_output_source_path')
    return path


def run(paired, output):
    from prototypes.go_comparison_probe import instrument_sources

    parent = read(paired / 'protocol.json')
    ready = read(paired / 'ready.json')
    if digest(paired / 'protocol.json') != ready['protocol_sha256']:
        raise ValueError('parent_protocol_changed')
    inventory = Path(parent['inventory'])
    cases = parent['cases']
    if len(cases) != 17 or len(set(cases)) != 17:
        raise ValueError('trial_denominator_changed')
    inputs, case_paths = {}, {}
    for case in cases:
        path = inventory / case / 'corpus.json'
        case_path = inventory / case / 'case.json'
        for name, value in [('corpus.json', path), ('case.json', case_path)]:
            if digest(value) != parent['input_sha256'][case][name]:
                raise ValueError('sealed_source_input_changed')
            inputs[str(value.resolve())] = digest(value)
        record = read(case_path)
        patch = Path(record['candidate_patch'])
        if digest(patch) != record['repository_provenance']['patch_sha256']:
            raise ValueError('candidate_patch_changed')
        inputs[str(patch.resolve())] = digest(patch)
        case_paths[case] = (path, patch)
    code_names = ['scripts/census_go_comparison_probes.py',
                  'prototypes/go_comparison_probe.py',
                  'tests/test_go_comparison_probe.py',
                  'tests/test_go_comparison_census.py',
                  'prototypes/patch_observation_priority.py',
                  'anchor_retrieval/syntax.py']
    hashes = {name: digest(ROOT / name) for name in code_names}
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'protocol.json', dict(
        version='patch-overlap-go-comparison-source-census-v1',
        cases=cases, input_sha256=inputs, code_sha256=hashes,
        selection='all Go production definitions with exact verified new patch lines',
        forbidden_inputs=['target labels', 'issue keywords', 'historical oracle answers',
                          'runtime outcomes', 'hidden tests', 'reference patches'],
        provider_calls=0, subject_executions=0,
        interpretation='source instrumentation support only; no path feasibility or oracle proof'))
    for name in hashes:
        target = output / 'code_snapshot' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    totals = {}
    for case, (corpus_path, patch_path) in case_paths.items():
        start = time.monotonic()
        corpus = read(corpus_path)
        sources, selected, unknowns = select_functions(corpus, patch_path.read_text())
        result = instrument_sources(sources, selected)
        write(output / case / 'selection.json', dict(functions=selected, unknowns=unknowns))
        write(output / case / 'instrumentation.json', result)
        files = {**result.get('files', {}), **result.get('runtime_files', {})}
        checksums = {}
        for name, code in sorted(files.items()):
            target = output / case / 'files' / _safe_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(code)
            checksums[name] = digest(target)
        write(output / case / 'files.json', checksums)
        totals[case] = dict(language=corpus['language'], source_files=len(sources),
                           selected_functions=len(selected),
                           supported_comparisons=len(result.get('comparisons', [])),
                           source_unknowns=len(unknowns),
                           instrumentation_unknowns=len(result.get('unknowns', [])),
                           output_files=len(files), elapsed_seconds=time.monotonic() - start)
        print(json.dumps(dict(case=case, **totals[case])), flush=True)
    write(output / 'summary.json', dict(cases=totals, trial_count=len(totals),
                                      provider_calls=0, subject_executions=0))
    if hashes != {name: digest(ROOT / name) for name in hashes}:
        raise ValueError('analysis_code_changed_no_seal')
    if any(digest(path) != expected for path, expected in inputs.items()):
        raise ValueError('analysis_input_changed_no_seal')
    write(output / 'seal.json', dict(files_sha256={str(path.relative_to(output)): digest(path)
                                                  for path in sorted(output.rglob('*')) if path.is_file()}))
    return dict(trials=len(totals), supported_comparisons=sum(row['supported_comparisons'] for row in totals.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--paired', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.paired, args.output)), flush=True)


if __name__ == '__main__':
    main()
