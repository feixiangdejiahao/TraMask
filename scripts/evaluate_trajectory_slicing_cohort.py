#!/usr/bin/env python3
"""Score frozen public slices against the 128 historical source quotations.

Labels enter here, after replay and slicing. Raw material retention, source
version alignment and coverage within one program view are separate measures.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from eviweave.anchors import SUFFIXES
from eviweave.artifacts import read_json, read_manifest, resolve_references, write_json
from eviweave.blobs import BlobStore
from eviweave.evidence import SourceGraph
from eviweave.pre_slice import covered, merge_ranges
from eviweave.source_text import decode_material
from eviweave.targets import read_target_source
from eviweave.history import read_context
from eviweave.trajectory import TrajectoryGraph
from run_slicing_pilot import token_ranges
from verify_pre_slice_five_pilot import original_sources

FR = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'
GOLD = ROOT / 'results/behavioral_masking/20261102_step_d_selectivity_n88_r01/quote_inventory.json'
PRIOR = ROOT / 'results/behavioral_masking/20261103_pre_slice_provenance_n88_r01/cases'


def compare_quote(mid, info, source, needle, views, strict_views, data_view, source_graphs):
    """Evaluate every occurrence of the cited text in this source version."""
    raw, target = source.encode(), needle.encode()
    key = info['path'], info['sha256']
    if Path(info['path']).suffix in SUFFIXES:
        if key not in source_graphs:
            source_graphs[key] = SourceGraph({'id': mid, 'path': info['path'], 'raw': raw})
        tree = source_graphs[key].root
    else:
        tree = None
    union = merge_ranges(r for _, ranges in views for r in ranges)
    candidates = []
    start = raw.find(target)
    while start >= 0:
        end = start + len(target)
        required = token_ranges(tree, start, end) if tree is not None else [[start, end]]
        core = token_ranges(tree, start, end, core=True) if tree is not None else required
        one = [name for name, ranges in views if required and all(covered(a, b, ranges) for a, b in required)]
        core_one = [name for name, ranges in views if core and all(covered(a, b, ranges) for a, b in core)]
        exact_one = [name for name, ranges in strict_views if core and all(covered(a, b, ranges) for a, b in core)]
        candidates.append({'material': mid, 'path': info['path'], 'sha256': info['sha256'], 'range': [start, end],
                           'same_program_view': bool(one), 'core_same_program_view': bool(core_one),
                           'data_view': data_view, 'exact_occurrence_core_view': bool(exact_one),
                           'core_union': bool(core) and all(covered(a, b, union) for a, b in core),
                           'views': core_one[:4]})
        start = raw.find(target, start + 1)
    return candidates


def evaluate(case, directory):
    sid = case['screen_id']
    run=directory.parent.parent;collection_run=read_json(run/'protocol.json')['collection_run']
    collection_dir=(run/collection_run).resolve()/'cases'/sid if collection_run is not None else directory
    manifest_path = collection_dir / 'replay/tests/manifest.json'
    quotes = [q for q in read_json(GOLD) if q['case_id'] == sid]
    status = read_json(directory / 'worker_result.json')
    result = {'id': sid, 'worker_returncode': status['returncode'], 'quotes': [],
              'directory': str(directory)}
    if not manifest_path.exists():
        result.update(stage='collection_failed', references=len(quotes))
        return result
    manifest = read_manifest(manifest_path); graph_path = Path(manifest['trajectory']); graph = TrajectoryGraph(graph_path).data
    materials = graph['materials']; blobs = BlobStore(graph_path.parent / 'blobs')
    slice_ready = (status['returncode'] == 0 and manifest['submission_state_validated'] and
                   (directory / 'slicing/summary.json').exists())
    after = defaultdict(list)
    for a, b, kind in graph['edges']: after[a].append((b, kind))
    raw_cache = {}; contexts = {}

    def text(material):
        info = materials[material]; key = info['path'], info['sha256']
        if key not in raw_cache:
            raw = blobs.read(info['sha256'])
            try:raw_cache[key] = decode_material(info['path'], raw)[0]
            except UnicodeDecodeError:raw_cache[key]=None
        return raw_cache[key]

    def producer_action(material):
        producer = materials[material]['producer']
        if producer is None: return None
        event = graph['events'][producer]
        return producer if event['kind'] == 'action' else event['action']

    def in_action(material, action):
        return producer_action(material) == action or any(
            b in graph['events'] and graph['events'][b]['kind'] != 'action' and graph['events'][b]['action'] == action
            for b, kind in after[material])

    # Program views refer to material occurrences. Equal source bytes can also
    # be compared separately without claiming identical execution context.
    material_views = defaultdict(list); content_views = defaultdict(list);data_views=set()
    target_path=directory/'slicing/targets.json'
    targets=resolve_references(read_json(target_path),directory/'slicing') if slice_ready else {'units':[]}
    units=targets['units'];selected_text={};selected_versions=set()
    if slice_ready:
        entries=resolve_references(read_json(directory/'slicing/material_entries.json'),directory/'slicing')
        selected_ids=set(entries['records'])
        for record in targets['records']:
            if record['id'] in selected_ids and record['source'] not in selected_text:
                selected_text[record['source']]=read_context(record['source'])
        for entry in entries['files']:
            material=entry['source'].rsplit('/',1)[1];info=materials[material]
            selected_versions.add((info['path'],info['sha256']))
    command_paths={(u['source'],u.get('inline'),u.get('write')):u['path'] for u in units}
    for path in sorted((directory / 'slicing/views').glob('*.json')) if slice_ready else []:
        view = resolve_references(read_json(path),directory/'slicing')
        if view.get('mode') in {'source_input','data'} and 'material' in view:data_views.add(view['material'])
        for file in view.get('files', []):
            mid = file['material']; info = materials[mid]; row = [path.name, file['ranges']]
            material_views[mid].append(row); content_views[info['path'], info['sha256']].append(row)
        if 'static_slice' in view and view['static_slice'] is not None:
            source = view['source']
            if isinstance(source,dict):
                source_path=command_paths[source['source'],source.get('inline'),source.get('write')]
                info={'path':source_path,'sha256':hashlib.sha256(read_target_source(source).encode()).hexdigest()}
            else:
                filename, _, fragment = source.partition('#/')
                if filename not in contexts: contexts[filename] = read_json(filename)
                collection, index = fragment.split('/')
                info = contexts[filename][collection][index if collection == 'materials' else int(index)]
            row=[path.name, view['static_slice']['ranges']]
            content_views[info['path'], info['sha256']].append(row)
            if 'material' in view:material_views[view['material']].append(row)
    originals = original_sources(case)
    old = {q['id']: q for q in read_json(PRIOR / (sid + '.json'))['quotes']}
    source_graphs = {}
    for quote in quotes:
        needle = quote['code'].strip(); origin = quote['source_audit']['cited_origin']
        expected = old[quote['id']]['original_spans']
        candidate_paths = set(); exact_versions = set()
        for source, a, b in expected:
            path, raw = originals[source]
            canonical = path if path.startswith('/') else '/app/' + path
            candidate_paths.add(canonical)
            exact_versions.add((canonical, hashlib.sha256(raw).hexdigest()))
        if '/files/' in origin:
            path = '/app/' + origin.split('/files/', 1)[1]
            candidate_paths.add(path); exact_versions.add((path, hashlib.sha256(Path(origin).read_bytes()).hexdigest()))
        raw_sources = [];forms=set();material_entry=False
        if origin.startswith('s') and '_c' in origin:
            call = collection_dir / 'replay/runtime/calls' / origin
            command = call / 'command.sh'
            if command.exists() and needle in command.read_text():
                raw_sources.append(str(command));forms.add('executed_command')
                material_entry|=str(command) in selected_text and needle in selected_text[str(command)]
            recorded = call / 'archived_expected.json'
            if recorded.exists():
                for key, value in read_json(recorded).items():
                    if key in {'output', 'output_head', 'output_tail'} and needle in value:
                        raw_sources.append(str(recorded) + '#/' + key)
                        forms.add('original_observation')
                        reference=str(recorded)+'#/'+key
                        material_entry|=reference in selected_text and needle in selected_text[reference]
        candidates = []
        for mid, info in materials.items():
            if info['kind'] not in {'file', 'code_input'}: continue
            exact = (info['path'], info['sha256']) in exact_versions
            related = in_action(mid, origin) and (not candidate_paths or info['path'] in candidate_paths)
            if not exact and not related: continue
            source = text(mid)
            if source is None or needle not in source: continue
            raw_sources.append(str(graph_path) + '#/materials/' + mid)
            forms.add(info['kind'])
            material_entry|=(info['path'],info['sha256']) in selected_versions
            key = info['path'], info['sha256']
            candidates.extend(compare_quote(mid, info, source, needle, content_views[key],
                                            material_views[mid], mid in data_views, source_graphs))
        if not slice_ready:
            for candidate in candidates:
                for key in ('same_program_view','core_same_program_view','data_view','exact_occurrence_core_view','core_union'):
                    candidate[key]=None
        result['quotes'].append({'id': quote['id'], 'old_native': old[quote['id']]['native'],
                                 'raw_retained': bool(raw_sources), 'raw_sources': raw_sources,
                                 'retention_forms':sorted(forms),
                                 'source_aligned': bool(candidates), 'candidates': candidates,
                                 'data_view':any(c['data_view'] for c in candidates) if slice_ready else None,
                                 'material_entry_recovered':material_entry if slice_ready else None,
                                 'analysis_recovered':(material_entry or any(c['core_same_program_view'] or c['data_view'] for c in candidates)) if slice_ready else None,
                                 'same_program_view': any(c['same_program_view'] for c in candidates) if slice_ready else None,
                                 'core_same_program_view': any(c['core_same_program_view'] for c in candidates) if slice_ready else None,
                                 'exact_occurrence_core_view': any(c['exact_occurrence_core_view'] for c in candidates) if slice_ready else None,
                                 'core_union': any(c['core_union'] for c in candidates) if slice_ready else None})
    summary_path = directory / 'summary.json'
    if summary_path.exists():
        summary = read_json(summary_path)
        result.update(submission_state_matches=summary['submission_state_matches'],
                      timeouts=len(summary['timeouts']), returncode_differences=len(summary['returncode_differences']))
    result.update(stage='evaluated' if slice_ready else 'slicing_unavailable', references=len(quotes), events=len(graph['events']),
                  materials=len(materials), edges=len(graph['edges']))
    return result


def summarize(rows):
    raw_keys=('raw_retained','source_aligned')
    slice_keys=('same_program_view','core_same_program_view','exact_occurrence_core_view','core_union','data_view','material_entry_recovered','analysis_recovered')
    totals = Counter({key:0 for key in ('references','raw_evaluated_references','slice_evaluated_references',
                      'old_native_slice_evaluated_references',*raw_keys,*slice_keys,
                      *('old_native_'+key for key in (*raw_keys,*slice_keys)))})
    for row in rows:
        totals['references'] += row['references']
        totals['raw_evaluated_references'] += len(row['quotes'])
        for q in row['quotes']:
            for key in raw_keys:
                totals[key] += q[key]
                if q['old_native']:totals['old_native_'+key] += q[key]
            if row['stage'] == 'evaluated':
                totals['slice_evaluated_references'] += 1
                if q['old_native']:totals['old_native_slice_evaluated_references'] += 1
                for key in slice_keys:
                    totals[key] += q[key]
                    if q['old_native']:totals['old_native_'+key] += q[key]
    return {'cases': len(rows), 'stages': Counter(r['stage'] for r in rows),
            'totals': dict(totals), 'new_llm_calls': 0,
            'cases_with_worker_errors': [r['id'] for r in rows if r['worker_returncode']],
            'quote_misses': [q['id'] for r in rows for q in r['quotes'] if not q['raw_retained']]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, nargs='+', required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+')
    args = parser.parse_args(); out = args.out.resolve(); out.mkdir(parents=True); (out / 'cases').mkdir()
    rows = []
    for case in read_json(FR / 'cases.json')['cases']:
        sid = case['screen_id']
        if args.cases and sid not in args.cases: continue
        candidates = [run.resolve() / 'cases' / sid for run in args.runs if (run / 'cases' / sid).exists()]
        row = evaluate(case, candidates[-1]); rows.append(row); write_json(out / 'cases' / (sid + '.json'), row)
        print(sid, row['stage'], flush=True)
    write_json(out / 'summary.json', summarize(rows))


if __name__ == '__main__': main()
