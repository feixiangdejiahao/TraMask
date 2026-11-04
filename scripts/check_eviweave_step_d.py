#!/usr/bin/env python3
"""Check the optimized D API on real A artifacts and the full public cohort."""
import argparse
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
import csv
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.history import history_records, read_context
from eviweave.invocations import commands
from eviweave.pre_slice import covered, merge_ranges
from eviweave.replay.trajectory import resolve_submission_actions
from eviweave.targets import locate_targets, read_target_source, targets_from_manifest
from verify_pre_slice_five_pilot import original_sources

FR = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
PREVIOUS = ROOT / 'results/behavioral_masking/20261103_pre_slice_provenance_n88_r01'
GOLD = ROOT / 'results/behavioral_masking/20261102_step_d_selectivity_n88_r01'
A = ROOT / 'results/behavioral_masking/20261101_step_a_simplification_r02'


def public_materials(case, directory):
    """Adapt frozen public text; D itself extracts writes and inline scripts."""
    directory.mkdir()
    actions, _ = resolve_submission_actions(read_json(Path(case['input_directory']) / 'trajectory.json'))
    tools, materials = {}, []
    tool_file = directory / 'tools.json'
    for action in actions:
        key = action['id'] + ':command'
        tools[key] = action['command']
        materials.append({'source': str(tool_file) + '#/' + key, 'text': action['command'], 'kind': 'command',
                          'action_id': action['id'], 'expected': action['expected']})
        for field in ('output', 'output_head', 'output_tail'):
            if field in action['expected']:
                key = action['id'] + ':' + field
                tools[key] = action['expected'][field]
                materials.append({'source': str(tool_file) + '#/' + key, 'text': tools[key],
                                  'kind': 'output', 'action_id': action['id'],'origin':'original'})
    write_json(tool_file, tools)
    submitted = {}
    inventory = read_json(FR / 'public_workspace_v3/cases' / case['screen_id'] / 'inventory.json')
    file_refs = directory / 'files'
    file_refs.mkdir()
    for index, entry in enumerate(inventory['entries']):
        if entry['status'] == 'stored' and entry['type'] == 'regular':
            submitted['/app/' + entry['path']] = entry['sha256']
            if entry['content_type'] != 'text_utf8':
                continue
            digest = entry['sha256']
            blob = FR / 'public_workspace_v3/cas/sha256' / digest[:2] / digest
            reference = file_refs / str(index)
            reference.symlink_to(blob)
            raw = blob.read_bytes()
            materials.append({'source': str(reference), 'text': raw.decode(), 'raw': raw,
                              'kind': 'file', 'path': '/app/' + entry['path'], 'sha256': digest})
    return materials, submitted, actions


def check_readback(result, materials=None):
    """Check complete B, emitted source coordinates, templates and byte metrics."""
    raw, intervals = {}, defaultdict(list)
    for unit in result['units']:
        key = unit['source'], unit.get('inline'), unit.get('write')
        if key not in raw:
            raw[key] = read_target_source(unit).encode()
        assert 0 <= unit['start'] < unit['end'] <= len(raw[key])
        assert all(unit['start'] <= a < b <= unit['end'] for a, b in unit['ranges'])
        for start, end in unit['anchors']:
            assert unit['start'] <= start < end <= unit['end']
            raw[key][start:end].decode()
        intervals[key].extend(unit['ranges'])
    assert result['metrics']['source_bytes'] == sum(b - a for spans in intervals.values() for a, b in merge_ranges(spans))
    assert result['metrics']['root_units'] == sum(bool(u['anchors']) for u in result['units'])
    assert result['metrics']['anchor_positions'] == sum(len(u['anchors']) for u in result['units'])
    assert sorted(i for group in result['syntax_templates'] for i in group) == list(range(len(result['units'])))
    assert len(result['syntax_templates']) == result['metrics']['syntax_template_jobs']
    contexts = {m['source']: m['text'] for m in materials} if materials is not None else {
        r['source']: read_context(r['source']) for r in result['records']}
    assert {source for source, text in contexts.items() if text is not None and text.strip()} == {r['source'] for r in result['records']}
    assert all(r['text'] in contexts[r['source']] for r in result['records'])
    return raw


def run_case(job):
    case, out = job
    sid = case['screen_id']
    materials, submitted, actions = public_materials(case, out / 'materials' / sid)
    inputs = FR / 'public_inputs' / sid
    # The frozen corpus has command-literal provenance. A's observed version
    # changes are tested separately on real manifests below.
    result = locate_targets((inputs / 'issue.md').read_text(), (inputs / 'patch.diff').read_text(),
                            materials, submitted, set())
    write_json(out / 'selections' / (sid + '.json'), result)
    raw_by_reference = check_readback(result, materials)
    command_actions = {m['source']: m['action_id'] for m in materials if m['kind'] == 'command'}
    file_paths = {m['source']: m['path'].removeprefix('/app/') for m in materials if m['kind'] == 'file'}
    write_ids, per_action = {}, defaultdict(int)
    for index, write in enumerate(commands(actions)['source_literals']):
        action = write['action_id']
        write_ids[action, per_action[action]] = f'H:{action}:{index:04}'
        per_action[action] += 1

    def canonical(unit):
        if 'write' in unit:
            return write_ids[command_actions[unit['source']], unit['write']]
        if 'inline' in unit:
            return f"I:{command_actions[unit['source']]}:{unit['inline']:04}"
        return 'F:' + file_paths[unit['source']]

    actual, intervals = {}, defaultdict(list)
    originals = original_sources(case)
    for unit in result['units']:
        identity = canonical(unit)
        raw = raw_by_reference[unit['source'], unit.get('inline'), unit.get('write')]
        assert raw == originals[identity][1]
        key = identity, unit['start'], unit['end']
        actual[key] = unit['ranges']
        intervals[identity].extend(unit['ranges'])
    # Manual quotations and previous experimental selections enter only after
    # the current D result has been written above.
    previous = read_json(PREVIOUS / 'selection' / (sid + '.json'))['arms']['roles32_authored']
    expected = {(u['source'], u['start'], u['end']): u['ranges'] for u in previous['units']}
    assert actual == expected, sid
    metrics = read_json(PREVIOUS / 'cases' / (sid + '.json'))['metrics']['roles32_authored']
    assert all(value == metrics[key] for key, value in result['metrics'].items()), sid
    previous_groups = {frozenset(map(tuple, group)) for group in previous['jobs']}
    groups = {frozenset((canonical(result['units'][i]), result['units'][i]['start'], result['units'][i]['end'])
                        for i in group) for group in result['syntax_templates']}
    assert groups == previous_groups
    intervals = {source: merge_ranges(spans) for source, spans in intervals.items()}
    previous_quotes = {q['id']: q for q in read_json(PREVIOUS / 'cases' / (sid + '.json'))['quotes']}
    quote_rows = []
    for quote in read_json(GOLD / 'quote_inventory.json'):
        if quote['case_id'] != sid:
            continue
        prior = previous_quotes[quote['id']]
        if prior['native']:
            for source, a, b in prior['original_spans']:
                assert originals[source][1][a:b] == quote['code'].strip().encode()
            retained = any(covered(a, b, intervals.get(source, [])) for source, a, b in prior['original_spans'])
        else:
            origin = quote['source_audit']['cited_origin']
            if origin.startswith('s') and '_c' in origin:
                refs = [m for m in materials if m['kind'] in {'command', 'output'} and m['action_id'] == origin]
            else:
                relative = origin.split('/files/', 1)[1]
                refs = [m for m in materials if m['kind'] == 'file' and m['path'].removeprefix('/app/') == relative
                        and hashlib.sha256(m['raw']).hexdigest() == hashlib.sha256(Path(origin).read_bytes()).hexdigest()]
            records = {r['source'] for r in result['records']}
            retained = any(quote['code'] in m['text'] and m['source'] in records for m in refs)
        quote_rows.append({'id': quote['id'], 'native': prior['native'], 'retained': retained})
    row = {'case_id': sid, 'task': case['task'], 'language': case['language'],
           **result['metrics'], 'records': len(result['records']), 'parse_errors': len(result['parse_errors']),
           'missing_patch_sources': result['missing_patch_sources'], 'matches_frozen_pilot': True,
           'code_references': sum(q['native'] for q in quote_rows),
           'code_retained': sum(q['native'] and q['retained'] for q in quote_rows),
           'other_references': sum(not q['native'] for q in quote_rows),
           'other_retained': sum(not q['native'] and q['retained'] for q in quote_rows), 'quotes': quote_rows}
    assert all(q['retained'] for q in quote_rows), sid
    write_json(out / 'cases' / (sid + '.json'), row)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--cases', nargs='*')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True)
    for name in ('materials', 'selections', 'cases', 'code'):
        (out / name).mkdir()
    code = [Path(__file__), ROOT / 'scripts/verify_pre_slice_five_pilot.py',
            *(ROOT / 'src/eviweave').glob('*.py')]
    digests = {}
    for path in code:
        relative = path.relative_to(ROOT)
        target = out / 'code' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
        digests[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    cases = read_json(FR / 'cases.json')['cases']
    if args.cases:
        cases = [c for c in cases if c['screen_id'] in args.cases]
    write_json(out / 'protocol.json', {
        'scope': 'Formal optimized D API on two actual A manifests and the frozen public cohort.',
        'case_ids': [c['screen_id'] for c in cases], 'test_selection': 'None; issue/Patch queries and all eligible historical sources.',
        'provenance': 'Actual A: observed source versions absent from initial snapshot, literal writes and inline scripts. Frozen corpus: command literals and inline scripts; no invented initial snapshot.',
        'evaluation': 'Exact candidate ranges, six aggregate metrics and template origins match the frozen recommended pilot; 98 original code spans and 30 original material references checked separately.',
        'source_sha256': digests, 'new_llm_calls': 0, 'docker_replays': 0})
    real = []
    for name, relative in [('full_history', 'recollected/S030/tests/manifest.json'),
                           ('live_checkpoint', 'live_collect/tests/manifest.json')]:
        manifest = A / relative
        result = targets_from_manifest(manifest)
        assert result['records'] == history_records(manifest)
        check_readback(result)
        write_json(out / (name + '.json'), result)
        real.append({'manifest': str(manifest), **result['metrics'], 'records': len(result['records']),
                     'parse_errors': len(result['parse_errors']), 'missing_patch_sources': result['missing_patch_sources']})
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(run_case, [(c, out) for c in cases]))
    summary = {'trajectories': len(results), 'tasks': len({c['task'] for c in cases}), 'real_A': real,
               'all_selections_match_frozen_pilot': all(r['matches_frozen_pilot'] for r in results),
               **{k: sum(r[k] for r in results) for k in (
                   'root_units', 'anchor_positions', 'units_with_support', 'source_bytes', 'syntax_template_jobs',
                   'syntax_template_bytes', 'code_references', 'code_retained', 'other_references', 'other_retained')},
               'cases_with_missing_patch_sources': [r['case_id'] for r in results if r['missing_patch_sources']],
               'new_llm_calls': 0, 'docker_replays': 0}
    write_json(out / 'summary.json', summary)
    with (out / 'cases.csv').open('w', encoding='utf-8', newline='') as stream:
        fields = ['case_id', 'task', 'language', 'root_units', 'anchor_positions', 'units_with_support',
                  'source_bytes', 'syntax_template_jobs', 'syntax_template_bytes', 'records',
                  'code_references', 'code_retained', 'other_references', 'other_retained', 'matches_frozen_pilot']
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows({key: row[key] for key in fields} for row in results)
    print(summary, flush=True)


if __name__ == '__main__':
    main()
