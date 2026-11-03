#!/usr/bin/env python3
"""Re-read original bytes and independently check every pilot range and origin."""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.anchors import SUFFIXES, parse_source
from eviweave.invocations import commands
from eviweave.pre_slice import covered, merge_ranges, template_key
from eviweave.replay.trajectory import resolve_submission_actions
from eviweave.shell import inline_sources

FR = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
GOLD = ROOT / 'results/behavioral_masking/20261102_step_d_selectivity_n88_r01'
CHANNEL = ROOT / 'results/behavioral_masking/20261102_validation_channels_n88_r03'
OLD = ROOT / 'results/behavioral_masking/20261102_validation_structural_n88_r01'


def original_sources(case):
    originals = {}
    actions, _ = resolve_submission_actions(read_json(Path(case['input_directory']) / 'trajectory.json'))
    for index, entry in enumerate(commands(actions)['source_literals']):
        originals[f"H:{entry['action_id']}:{index:04}"] = (entry['path'], entry['content'].encode())
    for action in actions:
        for index, entry in enumerate(inline_sources(action['command'])['sources']):
            originals[f"I:{action['id']}:{index:04}"] = (entry['path'], entry['text'].encode())
    inventory = read_json(FR / 'public_workspace_v3/cases' / case['screen_id'] / 'inventory.json')['entries']
    for entry in inventory:
        if entry['status'] == 'stored' and entry['type'] == 'regular' and entry['content_type'] == 'text_utf8':
            sha = entry['sha256']
            originals['F:' + entry['path']] = (entry['path'], (FR / 'public_workspace_v3/cas/sha256' / sha[:2] / sha).read_bytes())
    return originals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline-run', type=Path, default=OLD)
    parser.add_argument('--baseline-arm', default='scope_or_authored')
    parser.add_argument('--baseline-fields', nargs=2, default=['roots', 'positions'])
    parser.add_argument('--compare-baseline-ranges', action='store_true')
    args = parser.parse_args()
    args.out.mkdir(parents=True)
    (args.out / 'verifier.py').write_bytes(Path(__file__).read_bytes())
    protocol = read_json(args.run / 'protocol.json')
    gold = {q['id']: q for q in read_json(GOLD / 'quote_inventory.json')}
    quote_checks, totals = [], Counter()
    for case in read_json(FR / 'cases.json')['cases']:
        sid = case['screen_id']
        if sid not in protocol['case_ids']:
            continue
        originals = original_sources(case)
        selection = read_json(args.run / 'selection' / (sid + '.json'))
        result = read_json(args.run / 'cases' / (sid + '.json'))
        old = read_json(args.baseline_run / 'cases' / (sid + '.json'))['metrics'][args.baseline_arm]
        assert result['metrics']['baseline']['root_units'] == old[args.baseline_fields[0]]
        assert result['metrics']['baseline']['anchor_positions'] == old[args.baseline_fields[1]]
        if args.compare_baseline_ranges:
            previous = read_json(args.baseline_run / 'selection' / (sid + '.json'))['arms'][args.baseline_arm]
            current = selection['arms']['baseline']
            assert current['intervals'] == previous['intervals'] and current['jobs'] == previous['jobs']
            fields = ('source', 'start', 'end', 'ranges')
            assert [[u[k] for k in fields] for u in current['units']] == [[u[k] for k in fields] for u in previous['units']]
        authored = [(source, u['start'], u['end']) for source, (path, raw) in originals.items()
                    if source.startswith(('H:', 'I:')) and Path(path).suffix in SUFFIXES
                    for u in parse_source(path, raw)['units']]
        for arm, selected in selection['arms'].items():
            units = {(r['source'], r['start'], r['end']): r for r in selected['units']}
            flat_jobs = [tuple(key) for group in selected['jobs'] for key in group]
            assert set(flat_jobs) == units.keys() and len(flat_jobs) == len(units)
            collected = {}
            for unit in units.values():
                source, start, end = unit['source'], unit['start'], unit['end']
                raw = originals[source][1]
                assert 0 <= start < end <= len(raw)
                assert all(start <= a < b <= end for a, b in unit['ranges'])
                collected.setdefault(source, []).extend(unit['ranges'])
            assert {source: merge_ranges(spans) for source, spans in collected.items()} == selected['intervals']
            if 'dedup' in protocol['arms'][arm]:
                for group in selected['jobs']:
                    signatures = set()
                    for key in map(tuple, group):
                        path, raw = originals[key[0]]
                        signatures.add(template_key(path, hashlib.sha256(raw).hexdigest(), units[key]['ranges']))
                    assert len(signatures) == 1
            else:
                assert all(len(group) == 1 for group in selected['jobs'])
            byte_count = sum(b - a for spans in selected['intervals'].values() for a, b in spans)
            assert byte_count == result['metrics'][arm]['source_bytes']
            assert len(selected['jobs']) == result['metrics'][arm]['syntax_template_jobs']
            if 'authored' in protocol['arms'][arm]:
                assert all(covered(a, b, selected['intervals'].get(source, [])) for source, a, b in authored)
                totals['complete_authored_scopes_checked'] += len(authored)
        for row in result['quotes']:
            quote = gold[row['id']]
            origin = quote['source_audit']['cited_origin']
            for source, start, end in row['original_spans']:
                path, raw = originals[source]
                assert raw[start:end] == quote['code'].strip().encode()
                if origin.startswith('s') and '_c' in origin:
                    assert source.startswith('H:' + origin + ':') or source.startswith('I:' + origin + ':')
                else:
                    assert path.removeprefix('/app/') == origin.split('/files/', 1)[1]
                    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(Path(origin).read_bytes()).hexdigest()
            if row['native']:
                assert row['original_spans']
                for arm, selected in selection['arms'].items():
                    actual = any(covered(a, b, selected['intervals'].get(source, []))
                                 for source, a, b in row['original_spans'])
                    assert actual == row['arms'][arm]
            else:
                channel = read_json(CHANNEL / 'selection' / (sid + '.json'))
                if origin.startswith('s') and '_c' in origin:
                    history = read_json(FR / 'public_inputs' / sid / 'history.json')['actions']
                    action = next(a for a in history if a['id'] == origin)
                    texts = {'command': action['command'], **action['observation']}
                    actual = any(quote['code'] in texts[field][a:b]
                                 for field, windows in channel['windows'].get(origin, {}).items() for a, b in windows)
                else:
                    path = origin.split('/files/', 1)[1]
                    raw = originals['F:' + path][1]
                    assert hashlib.sha256(raw).hexdigest() == hashlib.sha256(Path(origin).read_bytes()).hexdigest()
                    actual = any(quote['code'] in raw.decode()[a:b] for a, b in channel['file_windows'].get(path, []))
                assert actual == row['non_AST_original_window']
            quote_checks.append(row['id'])
        totals['cases'] += 1
        totals['units_checked_across_arms'] += sum(len(a['units']) for a in selection['arms'].values())
    summary = {**dict(totals), 'unique_citations_checked': len(set(quote_checks)),
               'origin_and_literal_spans': 'passed', 'candidate_ranges_and_template_origins': 'passed',
               'baseline_matches_previous_all_88': True}
    write_json(args.out / 'verification.json', summary)
    print(summary, flush=True)


if __name__ == '__main__':
    main()
