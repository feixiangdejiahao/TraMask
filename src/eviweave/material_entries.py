"""Select and connect command, observation and data carriers to program views."""
from collections import defaultdict
from pathlib import PurePosixPath
import posixpath
import re

from .anchors import SUFFIXES, STRINGS
from .pre_slice import covered
from .regions import _decode_literal
from .retrieval import observed_action_jobs

VALIDATION = {'validation_or_script', 'program_execution', 'subject_execution',
              'module_execution', 'authored_validation_fragment'}


def data_entries(files, mentioned, paths):
    """Keep explicit data files and snapshots beside matched source files."""
    directories = {PurePosixPath(path).parent for path in paths}
    result = []
    for file in files:
        path = PurePosixPath(file['path'])
        if path.suffix in SUFFIXES:
            continue
        if file['path'] in mentioned:
            reason = 'explicit_path'
        elif (path.suffix == '.snap' and path.parent.name in {'snapshots', '__snapshots__'}
              and path.parent.parent in directories):
            reason = 'adjacent_snapshot'
        else:
            continue
        result.append({'source': file['source'], 'path': file['path'], 'reason': reason})
    return result


def select_material_entries(actions, names, changes, paths, action_ids, files):
    """Use source provenance, validation roles and structured read payloads.

    Actions are original recorded commands/observations. Returned entries are
    addresses, not copies of their text or inferred program-dependency edges.
    """
    rules = [{'calls': names, 'types': [], 'fields': [], 'input_tokens': []}]
    jobs = observed_action_jobs(actions, rules, list(changes))
    by_id = {action['id']: action for action in actions}
    selected = {identity: {'matched_source'} for identity in action_ids}
    mentioned = set()
    for job in jobs:
        reasons = set()
        if paths.intersection(job['paths']):
            reasons.add('matched_path')
        if VALIDATION.intersection(job['roles']):
            reasons.add('validation_or_execution')
        if 'structured_read' in job['roles']:
            reasons.add('structured_read')
        if reasons:
            selected.setdefault(job['action_id'], set()).update(reasons)
        if job['action_id'] in selected:
            mentioned.update(job['paths'])
    return {'actions': [{'action': identity, 'reasons': sorted(selected[identity])}
                        for identity in by_id if identity in selected],
            'files': data_entries(files, mentioned, paths | mentioned)}


class MaterialConnections:
    """Shared documents and source-qualified links; no extra operation pairs.

    Action scope, package execution and static path candidates are distinct
    from an observed operation-level read. File versions remain separate.
    """

    def __init__(self, materials, actions, *, root):
        self.root=root
        self.documents={};self.ids={}
        self.by_action=defaultdict(set);self.by_path=defaultdict(set);self.by_version=defaultdict(set)
        self.snapshots=defaultdict(set);self.features={}
        for material in materials:
            source=material['source'];kind=material['kind'];identity='D'+str(len(self.documents))
            assert source not in self.ids, 'Each document must have one source address'
            self.ids[source]=identity
            document={'id':identity,'source':source,'kind':kind,'text':material['text']}
            if kind=='file':
                document.update(path=material['path'],sha256=material['sha256'])
                self.by_path[material['path']].add(identity)
                self.by_version[material['path'],material['sha256']].add(identity)
                if material['path'].endswith('.snap') and material['text'] is not None:
                    match=re.search(r'(?m)^source:\s*(.+)$',material['text'])
                    if match:
                        path=posixpath.normpath(posixpath.join(root,match[1].strip()))
                        self.snapshots[path].add(identity)
            if kind=='output':document['origin']=material['origin']
            if 'source_error' in material:document['source_error']=material['source_error']
            if 'action_id' in material and material['action_id'] is not None:
                document['action']=material['action_id']
                self.by_action[material['action_id']].add(identity)
            self.documents[identity]=document
        self.jobs={j['action_id']:j for j in observed_action_jobs(actions,[],[])}
        self.by_module=defaultdict(set)
        for job in self.jobs.values():
            for module in job['modules']:
                base=posixpath.join(root,module.replace('.','/'))
                if any(path==base+'.py' or path.startswith(base+'/') for path in self.by_path):
                    self.by_module[module.split('.')[0]].add(job['action_id'])
        # Jest snapshots identify their source by filename rather than a header.
        for path in self.by_path:
            if PurePosixPath(path).parent.name=='__snapshots__' and path.endswith('.snap'):
                source=str(PurePosixPath(path).parent.parent/PurePosixPath(path).name.removesuffix('.snap'))
                self.snapshots[source].update(self.by_path[path])
        self.path_bytes={path.encode():path for path in self.by_path}

    def source_features(self, graph):
        key=graph.source['id']
        if key not in self.features:
            literals=[];modules=[];todo=[] if graph.issues else [graph.root]
            suffix=PurePosixPath(graph.source['path']).suffix
            path=posixpath.normpath(posixpath.join(self.root,graph.source['path']))
            while todo:
                node=todo.pop();todo.extend(reversed(node.named_children))
                span=[node.start_byte,node.end_byte]
                if node.type in STRINGS:
                    value,_,_,reason=_decode_literal(graph.raw,node,suffix)
                    if reason is None:
                        # Normalize each literal once per source version. Go
                        # strings may be arbitrary bytes, not Unicode text.
                        resolved={posixpath.normpath(posixpath.join(base.encode(),value))
                                  for base in (self.root,posixpath.dirname(path))}
                        literals.extend((span,self.path_bytes[value]) for value in resolved & self.path_bytes.keys())
                if suffix=='.py' and node.type=='import_from_statement':
                    name=node.child_by_field_name('module_name')
                    if name is not None:modules.append((span,graph.text(name).split('.')[0]))
                elif suffix=='.py' and node.type=='import_statement':
                    for child in node.named_children:
                        name=child.child_by_field_name('name') if child.type=='aliased_import' else child
                        modules.append((span,graph.text(name).split('.')[0]))
            self.features[key]=literals,modules
        return self.features[key]

    def links(self, sources, *, actions):
        """sources contains (SourceGraph, retained ranges), without reparsing."""
        links=set();paths=set();modules=set();owners=set(actions)
        for graph,ranges in sources:
            path=posixpath.normpath(posixpath.join(self.root,graph.source['path']))
            paths.add(path)
            for module in self.by_module:
                base=posixpath.join(self.root,module)
                if path==base+'.py' or path.startswith(base+'/'):modules.add(module)
            literals,imports=self.source_features(graph)
            modules.update(module for span,module in imports if covered(*span,ranges))
            for span,target in literals:
                if not covered(*span,ranges):continue
                paths.add(target)
                links.update((source,'literal_path_version_candidate',path) for source in self.by_path[target])
        for module in modules & self.by_module.keys():
            for action in self.by_module[module]:
                links.update((source,'package_execution_candidate',action) for source in self.by_action[action])
                owners.add(action)
        for action in owners:
            links.update((source,'action_material',action) for source in self.by_action[action])
            if action in self.jobs:
                for path in set(self.jobs[action]['paths']) & self.by_path.keys():
                    links.update((source,'command_path_version_candidate',action) for source in self.by_path[path])
        for path in paths:
            links.update((source,'snapshot_for_source',path) for source in self.snapshots[path])
        return [{'material':source,'relation':relation,'via':via} for source,relation,via in sorted(links)]

    def observed_links(self, context, materials, trajectory_source):
        """One observed IO group per execution, shared by its program views."""
        links=set()
        for direction in ('inputs','outputs'):
            for identity in context[direction]:
                material=materials[identity]
                if material['kind'] in {'file','code_input'}:
                    documents=self.by_version[material['path'],material['sha256']]
                    assert documents, 'Every observed file version must remain in the A/B material catalog'
                else:
                    documents={self.ids[trajectory_source+'#/materials/'+identity]}
                links.update((document,'observed_'+direction.removesuffix('s'),context['execution'])
                             for document in documents)
        return [{'material':document,'relation':relation,'via':execution}
                for document,relation,execution in sorted(links)]
