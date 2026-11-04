"""Behavior comparison after slicing, independent of experiment datasets.

Program projections share a view ID across source files. Original members,
execution context and material links stay attached to that view; partitioning
shares queries rather than selecting a permanent representative.
"""
from collections import defaultdict
import hashlib
from pathlib import Path

from .artifacts import read_json, read_manifest, resolve_references, write_json
from .behavior_clusters import BehaviorClusterIndex, cluster_queries, observed_fields
from .behavior_deltas import BehaviorDeltaIndex
from .evidence import SourceGraph
from .history import read_source_bytes
from .port_admission import PortAdmissionIndex, operation_endpoints
from .relational_alignment import RelationalAlignmentIndex, ports
from .slice_behavior import indexes, read_behavior_graph, write_behavior_graph
from .source_text import decode_material
from .targets import read_target_source


PARTITIONS = ('ports', 'relations', 'flow', 'boundary')


def index_views(sources, views):
    """Index each source once; project its operations into retained views."""
    selected = defaultdict(set)
    for view in views:
        selected[view['source']].update(view['nodes'])
    index = PortAdmissionIndex(sources, selected)
    records = [record for view in views for record in index.view_features(view)]
    return index, records


def query_partitions(index, records, views, field_names=(), *, modes=('ports',)):
    """Build class queries directly, computing old profiles only for alias bridges."""
    cluster = BehaviorClusterIndex(index, field_names)
    memberships, pairs = {}, {}
    # Raw member reads and their canonical calls can inhabit different
    # interface classes. Preserve those original-family bridges at class level.
    selected = defaultdict(set)
    for view in views:
        selected[view['source']].update(view['nodes'])
    original = None
    for mode in modes:
        codes, members, assignments = {}, defaultdict(set), {}
        for record in records:
            code = cluster.signature(record, mode)
            identity = codes.setdefault(code, len(codes))
            member = record['view'], *record['key']
            assignments[member] = identity
            members[identity].add(member)
        queries = cluster_queries(index, records, assignments)
        families = defaultdict(lambda: defaultdict(lambda: {'members': [], 'anchors': []}))
        for view in views:
            keys = {key for node in view['nodes'] for key in index.by_statement[view['source'], node]}
            for key in sorted(keys):
                canonical = index.aliases.get(key, key)
                identity = assignments[view['id'], *canonical]
                op = index.operations[key]
                row = key, view['nodes'], view['id']
                bucket = families[op['kind'], op['name']][identity]
                bucket['members'].append(row)
                if key in view['anchors']:
                    bucket['anchors'].append(row)
        for family in families.values():
            for left, a in family.items():
                if not a['anchors']:
                    continue
                for right, b in family.items():
                    if (left, right) in queries:
                        continue
                    # Common canonical families were already indexed above.
                    if len({x[2] for x in a['anchors']} | {y[2] for y in b['members']}) < 2:
                        continue
                    if original is None:
                        original = RelationalAlignmentIndex(index.sources, selected)
                    if any(x[2] != y[2] and original.profile(x[0], nodes=x[1])['components'] !=
                           original.profile(y[0], nodes=y[1])['components']
                           for x in a['anchors'] for y in b['members']):
                        queries.add((left, right))
        memberships[mode], pairs[mode] = members, queries
    return {'memberships': memberships, 'cluster_pairs': {'original': pairs},
            'metrics': {'arms': {mode: {'clusters': len(memberships[mode]), 'query_pairs': len(pairs[mode])}
                                 for mode in modes}}}


class BehaviorComparison:
    """Reusable indices for partitioning and concrete, role-aligned differences."""

    def __init__(self, sources, views, field_names=()):
        self.sources, self.views, self.field_names = sources, views, field_names
        self.index, self.records = index_views(sources, views)
        self.deltas = BehaviorDeltaIndex(self.index)
        self.by_member = {(r['view'], *r['key']): r for r in self.records}

    def align(self, left, right):
        a, b = self.by_member[tuple(left)], self.by_member[tuple(right)]
        assert a['interface'] == b['interface'], 'Operation alignment requires matching interfaces'
        aa, bb = [{p['role']: p for p in ports(self.index.operations[r['key']])} for r in (a, b)]
        return {'left': list(left), 'right': list(right),
                'ports': [{'role': role, 'left': aa[role], 'right': bb[role]} for role in sorted(aa.keys() & bb.keys())],
                'added_ports': sorted(bb.keys() - aa.keys()), 'removed_ports': sorted(aa.keys() - bb.keys()),
                'difference': self.deltas.difference(a, b),
                'source_edits': self.deltas.syntax_difference(a['key'], b['key'])}

    def partition(self, *, modes=('ports',)):
        return query_partitions(self.index, self.records, self.views, self.field_names, modes=modes)


def load_slice_comparison(directory):
    """Read the current F format once; do not expand trajectory closures."""
    directory = Path(directory).resolve()
    groups = [read_json(p) for p in sorted((directory / 'slices').glob('*.json'))]
    manifest = read_json(directory / 'summary.json')['manifest']
    manifest = resolve_references({'manifest': manifest}, directory)['manifest']
    manifest_data = read_manifest(manifest)
    view_paths = list(dict.fromkeys(view for group in groups for view in group['views']))
    views = [read_json(directory / name) for name in view_paths]
    files = []
    for view in views:
        if view['mode'] == 'source_input':
            files.append([])
        elif 'static_slice' in view:
            files.append([{'graph': view['graph'], **view['static_slice']}])
        else:
            files.append(view['files'])
    references = set(group['graph'] for group in groups)
    references.update(file['graph'] for row in files for file in row)
    sources, documents = {}, {Path(manifest): manifest_data}
    for reference in sorted(references):
        saved = read_behavior_graph(directory / reference)
        origin = resolve_references({'source': saved['origin']}, directory)['source']
        error = None
        if isinstance(origin, str):
            physical = read_source_bytes(origin,documents=documents)
            try:
                text, error = decode_material(saved['path'], physical)
            except UnicodeDecodeError as failure:
                text, error = None, str(failure)
            raw = physical if text is None else text.encode()
        else:
            raw = physical = read_target_source(origin).encode()
        assert hashlib.sha256(physical).hexdigest() == saved['sha256'], 'Comparison must use the sliced source version'
        graph = SourceGraph({'id': reference, 'path': saved['path'], 'raw': raw},source_error=error)
        assert graph.export_nodes() == saved['nodes'], 'Statement coordinates must match the slice graph'
        sources[reference] = graph, indexes(graph)[0]
    anchors = defaultdict(set)
    # Coordinates identify the root even when the view spans helpers/files.
    for group in groups:
        behavior = sources[group['graph']][1]
        by_statement = behavior._by_statement
        for view in group['views']:
            for port in group['ports']:
                for start, end in port['points']:
                    anchors[view].update((group['graph'], operation) for operation in
                                         operation_endpoints(by_statement[port['node']], start, end))
    projections = []
    for identity, (name, row) in enumerate(zip(view_paths, files)):
        for file in row:
            source = file['graph']
            projections.append({'id': identity, 'source': source,
                                'nodes': set(file['nodes'] + file['context_nodes']),
                                'anchors': {key for key in anchors[name] if key[0] == source}})
    patch = (Path(manifest_data['replay']) / 'inputs/model.patch').read_text()
    comparison = BehaviorComparison(sources, projections, observed_fields(patch))
    return comparison, views, view_paths


def slice_material_connections(directory, views):
    """Keep each execution's IO group shared until a candidate is read."""
    directory=Path(directory).resolve()
    material_pool = read_behavior_graph(directory / 'candidate_materials.json.gz')
    view_links = {str(identity): view['candidate_material_links'] for identity, view in enumerate(views)}
    materials = resolve_references(material_pool['documents'], directory)
    return {'documents': materials, 'views': view_links,
            'executions': material_pool['executions'],
            'view_executions': {str(i): view['execution'] for i, view in enumerate(views)
                                if view['execution'] is not None}}


def compare_slices(directory, out, *, modes=('ports',)):
    """Export candidates and difference profiles from a new slicing run."""
    out = Path(out)
    out.mkdir(parents=True)
    comparison, views, view_paths = load_slice_comparison(directory)
    materials=slice_material_connections(directory,views)
    result = comparison.partition(modes=modes)
    write_behavior_graph(out / 'memberships.json.gz', {
        mode: {str(c): sorted(rows) for c, rows in groups.items()} for mode, groups in result['memberships'].items()})
    # Lifted queries are the current domain consumed by candidate-materials.
    write_behavior_graph(out / 'cluster_pairs.json.gz', {
        'original': {mode: sorted(rows) for mode, rows in result['cluster_pairs']['original'].items()}})
    write_behavior_graph(out / 'candidate_materials.json.gz', materials)
    profiles = {}
    for record in comparison.records:
        facets = comparison.deltas.facets(record)
        code = tuple(sorted(facets.items(), key=repr))
        if code not in profiles:
            profiles[code] = {'facets': [[list(address), *values] for address, values in code], 'members': []}
        profiles[code]['members'].append([record['view'], *record['key']])
    write_behavior_graph(out / 'difference_profiles.json.gz', list(profiles.values()))
    summary = {**result['metrics'], 'slices': str(Path(directory).resolve()),
               'source_graphs': len(comparison.sources), 'views': len(view_paths),
               'material_only_views': sorted(set(range(len(view_paths))) - {v['id'] for v in comparison.views}),
               'occurrences': len(comparison.records), 'difference_profiles': len(profiles),
               'candidate_materials': len(materials['documents']), 'view_paths': view_paths,
               'parse_issues': {source: graph.issues for source, (graph, _) in comparison.sources.items() if graph.issues}}
    write_json(out / 'summary.json', summary)
    return summary
