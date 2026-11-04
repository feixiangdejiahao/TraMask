#!/usr/bin/env python3
"""Count frozen D/F pair domains, then evaluate held-out human references."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from eviweave.artifacts import read_json, write_json
from eviweave.behavior import BehaviorIndex
from eviweave.evidence import SourceGraph
from eviweave.relational_alignment import RelationalAlignmentIndex
from eviweave.slicing import ContextProgram
from verify_pre_slice_five_pilot import FR, original_sources

OLD = ROOT/'results/behavioral_masking/20261103_joint_pipeline_alignment_n88_r03'
SPANS = ROOT/'results/behavioral_masking/20261103_slicing_pilot_n88_r06'


def write_gzip(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, separators=(',', ':'))


def view_pair_counts(index, records, anchor_views, groups, domains):
    """Deduplicate operation correspondences into directed F-view pairs."""
    view_ids = {(source,i): n for n,(source,i) in enumerate(
        (source,i) for source,r in records.items() for i in range(len(r['views'])))}
    statements = defaultdict(int)
    for (source,i),identity in view_ids.items():
        for f in records[source]['views'][i]['files']:
            for node in f['nodes'] + f['context_nodes']:
                statements[f['material'],node] |= 1 << identity
    member_masks, anchor_masks = [], []
    for g in groups:
        mask = 0
        for key in g['members']:
            mask |= statements[key[0], index.operations[tuple(key)]['statement']]
        member_masks.append(mask)
        anchor_masks.append({view_ids[v] for key in g['anchors'] for v in anchor_views[tuple(key)]})
    changed = defaultdict(int)
    for domain in domains:
        family=domain['groups'];suffix=[0]*(len(family)+1)
        for j in range(len(family)-1,-1,-1):suffix[j]=suffix[j+1]|member_masks[family[j]]
        prefix=0
        for j,group in enumerate(family):
            others=prefix|suffix[j+1]
            for left in anchor_masks[group]:changed[left] |= others & ~(1 << left)
            prefix |= member_masks[group]
    return {'directed_changed_view_pairs':sum(bits.bit_count() for bits in changed.values()),
            'views_with_changed_partner':sum(bool(bits) for bits in changed.values()),
            'all_directed_view_pairs':len(view_ids)*(len(view_ids)-1)}


def prepare_case(case):
    sid = case['screen_id']
    originals = original_sources(case)
    selection = read_json(OLD/'cases'/sid/'selection.json')
    sources, selected, records = {}, {}, {}
    for source, file in selection['sources'].items():
        path, raw = originals[source]
        record = read_json(OLD/'cases'/sid/file)
        assert hashlib.sha256(raw).hexdigest() == record['sha256']
        graph = SourceGraph({'id': source, 'path': path, 'raw': raw})
        # Frozen AST IDs belong to an older parser/statement graph. Byte
        # coordinates are the source-version invariant; rebuild F from them.
        mapped=defaultdict(lambda: {'points':set(),'entries':set()})
        unmapped=[]
        for group in record['groups']:
            for port in group['ports']:
                for a,b in port['points']:
                    criterion=graph.criterion(a,b)
                    if criterion is None:
                        unmapped.append([a,b]);continue
                    item=mapped[criterion['node']]
                    item['points'].add((a,b));item['entries'].update(port['entries'])
        program=ContextProgram.from_source(graph)
        rebuilt=program.grouped_slices(source,set(mapped))
        record={'source':source,'path':path,'sha256':record['sha256'],'issues':graph.issues,
                'unmapped_public_points':sorted(set(map(tuple,unmapped))),
                'views':[row['view'] for row in rebuilt],
                'groups':[{'group':row['group'],'view':i,
                           'ports':[{'node':n,'points':sorted(mapped[n]['points']),'entries':sorted(mapped[n]['entries'])}
                                    for n in row['group']['matches']]}
                          for i,row in enumerate(rebuilt)]}
        nodes = {n for view in record['views'] for f in view['files']
                 if f['material'] == source for n in f['nodes'] + f['context_nodes']}
        assert not nodes or max(nodes) < len(graph.nodes), (sid, source)
        sources[source] = graph, BehaviorIndex(graph)
        selected[source], records[source] = nodes, record
    index = RelationalAlignmentIndex(sources, selected)
    # Exact D expression positions first; smaller containing expressions handle
    # token positions. A containing test callback is not expanded into seeds.
    by_source = defaultdict(list)
    for key, op in index.operations.items():
        by_source[key[0]].append((op['expression_range'], key))
    anchors, unmatched, anchor_views = set(), [], defaultdict(set)
    for source, record in records.items():
        points = {tuple(p) for group in record['groups'] for port in group['ports'] for p in port['points']}
        views_for_point=defaultdict(set)
        for group in record['groups']:
            for port in group['ports']:
                for point in port['points']:views_for_point[tuple(point)].add((source,group['view']))
        for a, b in sorted(points):
            containing = [(e-s, key) for (s, e), key in by_source[source] if s <= a and b <= e]
            if containing:
                key=min(containing)[1];anchors.add(key)
                anchor_views[key].update(views_for_point[a,b])
            else:
                unmatched.append({'source': source, 'range': [a,b]})
    return index, records, by_source, anchors, unmatched, anchor_views


def run_case(job):
    case, out = job
    sid=case['screen_id'];started=time.perf_counter()
    index,records,by_source,anchors,unmatched,anchor_views=prepare_case(case)
    groups, domains = index.grouped_domains(anchors)
    group_for = {tuple(key): i for i, g in enumerate(groups) for key in g['members']}
    active_names = {(d['kind'],d['name']) for d in domains}
    bridges = index.interface_pairs()
    metrics = {'case': sid, 'task': case['task'], 'language': case['language'],
               'source_versions': len(index.sources), 'slice_views': sum(len(r['views']) for r in records.values()),
               'operations': len(index.operations), 'operation_anchors': len(anchors),
               'nonoperation_anchor_positions': len(unmatched),
               'unrestricted_directed_pairs': len(anchors) * (len(index.operations)-1),
               'same_operation_pairs': sum(d['occurrence_pairs'] for d in domains),
               'different_relation_pairs': sum(d['changed_occurrence_pairs'] for d in domains),
               'profile_comparisons': sum(d['profile_pairs'] for d in domains),
               'profile_groups': len(groups), 'local_producer_consumer_edges': len(bridges),
               'build_seconds': time.perf_counter()-started}
    metrics.update(view_pair_counts(index,records,anchor_views,groups,domains))
    directory = out/'cases'/sid
    write_gzip(directory/'domains.json.gz', {'groups': groups, 'domains': domains,
                  'profiles': list(index.profiles.values()),
                  'components': [{'kind': k, 'sha256': sha, 'value': value}
                                 for (k,sha),value in index.components.items()],
                  'local_interfaces': bridges, 'unmatched_anchor_positions': unmatched})
    write_json(directory/'metrics.json', metrics)
    # Evaluation starts only after the complete candidate domains are frozen.
    previous = read_json(OLD/'cases'/sid/'evaluation.json')['quotes']
    quote_spans = {q['id']: q['alternatives'] for q in read_json(SPANS/'cases'/sid/'evaluation.json')['quotes']}
    evaluations = []
    for quote in previous:
        endpoints = []
        for alternative in quote_spans[quote['id']]:
            source, (a,b) = alternative['source'], alternative['span']
            for (s,e), key in by_source[source]:
                if not (a < e and s < b):
                    continue
                group = groups[group_for[key]]
                if (group['kind'], group['name']) not in active_names:
                    continue
                other = [i for i,g in enumerate(groups) if g['anchors'] and
                         (g['kind'],g['name']) == (group['kind'],group['name']) and i != group_for[key]]
                if other:
                    endpoints.append({'source': source, 'range': [s,e], 'group': group_for[key],
                                      'anchor_profile_groups': other})
        evaluations.append({'id': quote['id'], 'previous_program_retained': quote['program'],
                            'previous_material_retained': quote['material'],
                            'changed_pair_endpoint_in_quote': bool(endpoints), 'endpoints': endpoints,
                            'interpretation': 'endpoint overlap only; required semantic delta not established'})
    write_gzip(directory/'reference_endpoints.json.gz', evaluations)
    print(sid, metrics['operations'], metrics['different_relation_pairs'],
          round(metrics['build_seconds'],1), 'seconds', flush=True)
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--cases', nargs='+')
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    cases = read_json(FR/'cases.json')['cases']
    if args.cases:
        cases = [c for c in cases if c['screen_id'] in args.cases]
    out = args.out.resolve();out.mkdir(parents=True)
    code = out/'code';code.mkdir()
    for path in ['src/eviweave/relational_alignment.py', 'scripts/pilot_port_relations.py']:
        (code/Path(path).name).write_bytes((ROOT/path).read_bytes())
    write_json(out/'protocol.json', {'case_ids': [c['screen_id'] for c in cases],
        'input': str(OLD), 'seed': 'all frozen D expression points inside retained F statement nodes',
        'pair_domain': 'directed anchor occurrence to another same kind/name operation occurrence',
        'profile_groups': 'comparison sharing only; every original occurrence remains a member',
        'difference': 'syntactic and conditional static relations, not semantic incompatibility',
        'manual_labels': 'evaluation only after writing complete pair domains',
        'material_only_and_cross_api': 'not counted as recovered by the operation-pair channel',
        'new_model_requests': 0})
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        rows = list(pool.map(run_case, [(case,out) for case in cases]))
    write_json(out/'counts.json', rows)
    fields = ['source_versions','slice_views','operations','operation_anchors','nonoperation_anchor_positions',
              'unrestricted_directed_pairs','same_operation_pairs','different_relation_pairs',
              'profile_comparisons','profile_groups','local_producer_consumer_edges']
    fields += ['directed_changed_view_pairs','views_with_changed_partner','all_directed_view_pairs']
    write_json(out/'summary.json', {'trajectories': len(rows), 'distinct_tasks': len({r['task'] for r in rows}),
                                  **{f: sum(r[f] for r in rows) for f in fields}})


if __name__ == '__main__':
    main()
