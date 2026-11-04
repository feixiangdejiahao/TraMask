"""Versioned file/stream provenance. Chronology resolves state, not causality."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shlex

from .artifacts import read_json, write_json
from .blobs import BlobStore
from .shell import inline_sources,interpreter_entry

SOURCE_USES={'reads','maps','uses_code','bytecode_equivalent'}


def read_trace(result):
    return [json.loads(raw) for raw in (Path(result['trace'])/'events.jsonl').read_text().splitlines()]


class Trajectory:
    def __init__(self,directory):
        self.directory=Path(directory)
        self.store=BlobStore(self.directory/'blobs')
        self.events={};self.materials={};self.edges=[];self.current={};self.initial={};self.changes=[]
        self.last_input={};self.issues=[];self.position=0

    def material(self,version,producer=None,*,kind='file'):
        identity='M'+str(len(self.materials))
        self.materials[identity]={'kind':kind,**version,'producer':producer}
        return identity

    def edge(self,source,target,kind):
        self.edges.append([source,target,kind])

    def blob(self,raw):
        return self.store.put(raw)

    def consumed(self,execution,event):
        previous=self.last_input.get(execution)
        if previous is not None:self.edge(previous,event,'input_prefix')
        self.last_input[execution]=event

    def output_dependencies(self,execution,event):
        if execution in self.last_input:self.edge(self.last_input[execution],event,'process_may_depend')

    def start(self,snapshot):
        for row in snapshot['files']:
            if row['kind']=='file':
                identity=self.material({k:row[k] for k in ('path','sha256')})
                self.current[row['path']]=identity
        self.initial=dict(self.current)

    def observed(self,version):
        path=version['path'];old=self.current.get(path)
        if old is not None and self.materials[old]['sha256']==version['sha256']:return old
        identity=self.material(version)
        if not version['unlinked']:
            self.current[path]=identity
            self.changes.append([self.position,path,identity])
        return identity

    def generated(self,event,version,previous,*,retains=False):
        old=self.observed(previous) if previous is not None else None
        identity=self.material(version,event)
        self.edge(event,identity,'produces')
        if old is not None:
            self.materials[identity]['previous']=old
            if retains:self.edge(old,event,'retained_bytes')
        if not version['unlinked']:
            self.current[version['path']]=identity
            self.changes.append([len(self.events)-1,version['path'],identity])
        return identity

    def add_action(self,action,result,rows):
        directory=Path(result['trace']);action_id=action['id'];channels=defaultdict(lambda:{'write':[],'read':[]});stdin_reads=defaultdict(list)
        inline_hints=inline_sources(action['command'])['sources'];processes={};forks={}
        self.store.merge(BlobStore(directory/'blobs'))
        for row in rows:
            identity=action_id+':'+str(row['id'])
            execution=action_id+':'+str(row['execution'])
            event={k:v for k,v in row.items() if k not in {'id','version','previous','executable','execution'}}
            event.update(action=action_id,execution=execution,ordinal=len(self.events))
            self.events[identity]=event
            self.position=event['ordinal']
            kind=row['kind']
            if kind=='exec':
                if row['pid'] in processes:self.output_dependencies(processes[row['pid']],identity)
                if row['pid'] in forks:self.edge(forks.pop(row['pid']),identity,'starts')
                self.last_input[execution]=identity
                if row['executable'] is not None:
                    material=self.observed(row['executable']);self.edge(material,identity,'executes_binary')
                    event['executable']=material
                sources=inline_sources(shlex.join(row['argv']))['sources']
                sources.extend(s for s in inline_hints if s['text'] in row['argv'][1:])
                source_values=set()
                for source in sources:
                    if (source['path'],source['text']) in source_values:continue
                    source_values.add((source['path'],source['text']))
                    raw=source['text'].encode();digest=self.blob(raw)
                    material=self.material({'path':source['path'],'sha256':digest,'bytes':len(raw)},action_id,kind='code_input')
                    self.edge(action_id,material,'supplies_code');self.edge(material,identity,'uses_code')
            elif kind=='fork':
                self.output_dependencies(execution,identity)
                forks[row['child']]=identity;processes[row['child']]=execution
            elif kind in {'read','mapped'}:
                material=self.observed(row['version']);event['material']=material
                self.edge(material,identity,'reads' if kind=='read' else 'maps')
                self.consumed(execution,identity)
            elif kind in {'write','file_open','file_change','file_copy'}:
                previous=row['previous']
                retains=(kind=='write' and previous is not None and
                         (row['offset']>0 or row['bytes']<previous['bytes']))
                if kind=='file_copy':
                    copied=self.observed(row['source']);self.edge(copied,identity,'copies_bytes');event.pop('source')
                event['material']=self.generated(identity,row['version'],previous,retains=retains)
                self.output_dependencies(execution,identity)
            elif kind in {'stream_read','stream_write'}:
                material=self.material({'path':'<stream:'+row['channel']+'>','sha256':row['data'],'bytes':row['bytes'],'channel':row['channel']},
                                       identity if kind=='stream_write' else None,kind='stream')
                event['material']=material
                self.edge(identity,material,'produces') if kind=='stream_write' else self.edge(material,identity,'reads')
                direction='write' if kind=='stream_write' else 'read';channels[row['channel']][direction].append(identity)
                if kind=='stream_read':
                    self.consumed(execution,identity)
                    if row['descriptor']==0:stdin_reads[execution].append(identity)
                else:self.output_dependencies(execution,identity)
            elif kind=='remove':
                old=self.current.pop(row['path'],None)
                if old is not None:event['removed']=old
                self.changes.append([event['ordinal'],row['path'],None])
            elif kind=='rename':
                source=row['path'];destination=row['destination']
                if row['previous'] is not None:self.observed(row['previous'])
                moving=[(p,m) for p,m in self.current.items() if p==source or p.startswith(source+'/')]
                for path,old in moving:
                    self.current.pop(path);self.changes.append([event['ordinal'],path,None])
                    version={k:v for k,v in self.materials[old].items() if k not in {'producer','previous','kind'}}
                    version.update(path=destination+path[len(source):],unlinked=False)
                    if path==source and row['version'] is not None:version=row['version']
                    new=self.generated(identity,version,None);self.edge(old,identity,'moves_bytes')
            elif kind=='exit':
                self.output_dependencies(execution,identity)
            elif kind.startswith('unresolved') or kind=='observer_artifact_access':
                self.issues.append(identity)
            if row.get('binding')=='concurrent_read_unresolved':self.issues.append(identity)
            if row.get('bytecode_source') is not None:
                binding=row['bytecode_source']
                codes=[]
                if 'equivalent_versions' in binding:
                    for version in binding['equivalent_versions']:
                        candidates=[m for m,v in self.materials.items() if v['kind']=='file' and v['path']==version['path'] and v['sha256']==version['sha256']]
                        codes.extend(candidates)
                elif 'version' in binding and binding['equivalent']:codes.append(self.observed(binding['version']))
                for code in codes:self.edge(code,identity,'bytecode_equivalent')
                if codes:event['bytecode_source']={'materials':codes,'basis':binding['basis'] if 'basis' in binding else 'bytecode_equivalence'}
                elif 'equivalent_versions' in binding:event['bytecode_source']={'materials':[], 'basis':binding['basis'],'reason':'no_saved_source_matches_cached_code'}
            processes[row['pid']]=execution
        hints={hashlib.sha256(s['text'].encode()).hexdigest():Path(s['path']).suffix for s in inline_hints}
        for execution,chunks in stdin_reads.items():
            argv=self.events[execution]['argv'];name=Path(argv[0]).name
            raw=b''.join(self.store.read(self.events[e]['data']) for e in chunks)
            digest=hashlib.sha256(raw).hexdigest();suffix=hints.get(digest)
            if suffix is None and (re.fullmatch(r'python[\d.]*',name) or name in {'node','nodejs','tsx','ts-node'}):
                if interpreter_entry(argv)[0]=='stdin':suffix='.py' if name.startswith('python') else '.ts' if name in {'tsx','ts-node'} else '.js'
            if suffix is None:continue
            self.blob(raw)
            material=self.material({'path':'<stdin>'+suffix,'sha256':digest,'bytes':len(raw)},kind='code_input')
            for e in chunks:self.edge(self.events[e]['material'],material,'concatenates')
            if chunks:self.edge(material,chunks[-1],'uses_code')
        # Single-channel byte agreement establishes transfers across split IO.
        for channel,parts in channels.items():
            writes,reads=parts['write'],parts['read']
            data=lambda event:self.store.read(self.events[event]['data'])
            produced=b''.join(map(data,writes));consumed=b''.join(map(data,reads))
            if not reads or not writes:continue
            writers={self.events[e]['execution'] for e in writes}
            readers={self.events[e]['execution'] for e in reads}
            if produced!=consumed or len(writers)!=1 or len(readers)!=1:
                self.issues.append({'kind':'channel_transfer_unresolved','action':action_id,'channel':channel});continue
            spans=[];at=0
            for event in writes:spans.append((at,at+self.events[event]['bytes'],event));at=spans[-1][1]
            at=0
            for read in reads:
                end=at+self.events[read]['bytes']
                for a,b,write in spans:
                    if a<end and at<b:self.edge(self.events[write]['material'],self.events[read]['material'],'stream_transfer')
                at=end
        command=os.path.relpath(directory.parent/'command.sh',self.directory)
        original=os.path.relpath(directory.parent/'archived_expected.json',self.directory)
        replay_output=os.path.relpath(directory.parent/'output.bin',self.directory)
        self.events[action_id]={'kind':'action','command':command,
                                'original':original,
                                'replay_output':replay_output,
                                'returncode':result['returncode'],'timed_out':result['timed_out'],'ordinal':len(self.events)}
        output=(directory.parent/'output.bin').read_bytes();digest=self.blob(output)
        aggregate=self.material({'path':'<replay-output:'+action_id+'>','sha256':digest,'bytes':len(output),
                                 'source':replay_output,'origin':'replay'},action_id,kind='action_output')
        self.edge(action_id,aggregate,'replay_observation')
        for event in channels['stdout']['write']:self.edge(self.events[event]['material'],aggregate,'stdout_contribution')
        for field in ('output','output_head','output_tail'):
            if field not in action['expected']:continue
            raw=action['expected'][field].encode();digest=self.blob(raw)
            material=self.material({'path':'<original-output:'+action_id+':'+field+'>','sha256':digest,'bytes':len(raw),
                                    'source':original+'#/'+field,'origin':'original'},action_id,kind='recorded_output')
            self.edge(action_id,material,'recorded_observation')

    def finish(self,snapshot):
        self.position=len(self.events)
        submitted={r['path']:r for r in snapshot['files'] if r['kind']=='file'}
        for path,row in submitted.items():
            self.observed({'path':path,'sha256':row['sha256'],'unlinked':False})
        for path in list(self.current):
            if path.startswith('/app/') and path not in submitted:self.current.pop(path)
        value={'initial':self.initial,'submitted':{p:self.current[p] for p in submitted},
               'materials':self.materials,'events':self.events,'edges':self.edges,
               'changes':self.changes,'issues':self.issues}
        write_json(self.directory/'trajectory.json',value)
        return value


class TrajectoryGraph:
    def __init__(self,path):
        self.path=Path(path).resolve();self.data=read_json(self.path)
        self.materials=self.data['materials'];self.events=self.data['events']
        def resolved(reference):
            filename,separator,fragment=reference.partition('#')
            return str((self.path.parent/filename).resolve())+separator+fragment
        for material in self.materials.values():
            if 'source' in material:material['source']=resolved(material['source'])
        for event in self.events.values():
            if event['kind']=='action':
                for key in ('command','original','replay_output'):event[key]=resolved(event[key])
        self.before=defaultdict(list);self.after=defaultdict(list)
        self.by_execution=defaultdict(list);self.by_source=defaultdict(list)
        self.bytecode_sources={}
        for a,b,kind in self.data['edges']:
            self.before[b].append((a,kind));self.after[a].append((b,kind))
        for event,row in self.events.items():
            if row['kind']!='action':self.by_execution[row['execution']].append(event)
        for identity,m in self.materials.items():
            if m['kind'] in {'file','code_input'}:
                self.by_source[m['path'],m['sha256']].extend(b for b,k in self.after[identity] if k in SOURCE_USES)

    def state_at(self,event):
        state=dict(self.data['initial']);ordinal=self.events[event]['ordinal']
        for position,path,material in self.data['changes']:
            if position>ordinal:break
            if material is None:state.pop(path,None)
            else:state[path]=material
        return state

    def consumers(self,path,digest):
        return sorted(set(self.by_source[path,digest]),key=lambda e:self.events[e]['ordinal'])

    def static_context(self,material):
        """Bind unexecuted source to its creation or owning snapshot."""
        info=self.materials[material];producer=info['producer']
        if producer is not None:
            state=self.state_at(producer);basis='source_creation_snapshot'
        elif material in self.data['submitted'].values():
            state=dict(self.data['submitted']);basis='submission_snapshot'
        else:
            state=dict(self.data['initial']);basis='initial_snapshot'
        state[info['path']]=material
        return {'execution':None,'source_versions':{p:[m] for p,m in state.items()},'input_versions':{},
                'source_basis':{m:basis for m in state.values()},'unresolved_versions':{},'unresolved_bytecode_sources':[]}

    def context(self,event):
        execution=self.events[event]['execution'];state={p:[m] for p,m in self.state_at(execution).items()}
        basis={m:'snapshot' for versions in state.values() for m in versions}
        for m,k in self.before[execution]:
            if k=='uses_code':basis[m]='observed_code_input'
        reads=defaultdict(set)
        for e in self.by_execution[execution]:
            v=self.events[e]
            for material,kind in self.before[e]:
                if kind=='uses_code':basis[material]='observed_code_input'
            if v['kind'] in {'read','mapped'}:
                material=self.materials[v['material']];reads[material['path']].add(v['material'])
                basis[v['material']]=v['kind']
        for path,versions in reads.items():state[path]=sorted(versions)
        unresolved_bytecode=[]
        for path,versions in list(reads.items()):
            if not path.endswith('.pyc'):continue
            filename=Path(path).name.split('.cpython-',1)[0]+'.py' if '/__pycache__/' in path else Path(path).name[:-1]
            source=str(Path(path).parent.parent/filename) if '/__pycache__/' in path else str(Path(path).with_suffix('.py'))
            if source in reads:continue
            candidates=set()
            for e in self.by_execution[execution]:
                row=self.events[e]
                if row['kind'] in {'read','mapped'} and row['material'] in versions and row.get('bytecode_source') is not None:
                    binding=row['bytecode_source']
                    if binding.get('basis') in {'bytecode_equivalence','pytest_bytecode_equivalence'}:candidates.update(binding['materials'])
            for version in versions:
                if version not in self.bytecode_sources:
                    ancestors=self.slice([version],direction='backward')['materials']
                    self.bytecode_sources[version]=[m for m in ancestors if self.materials[m]['kind']=='file' and self.materials[m]['path']==source]
                if not candidates:candidates.update(self.bytecode_sources[version])
            if candidates:
                state[source]=sorted(candidates);reads[source].update(candidates)
                for m in candidates:basis[m]='compiled_source_relation'
            elif source in state:unresolved_bytecode.append(source)
        return {'execution':execution,'source_versions':state,'input_versions':{p:sorted(v) for p,v in reads.items()},'source_basis':basis,
                'unresolved_bytecode_sources':unresolved_bytecode,
                'unresolved_versions':{p:sorted(v) for p,v in reads.items() if len({self.materials[m]['sha256'] for m in v})>1}}

    def slice(self,seeds,*,direction='both',inputs=()):
        backward=set(seeds)|set(inputs);todo=list(backward)
        while todo:
            node=todo.pop()
            for predecessor,kind in self.before[node]:
                if predecessor not in backward:backward.add(predecessor);todo.append(predecessor)
        forward=set(seeds);todo=list(seeds)
        if direction=='both':
            while todo:
                node=todo.pop()
                for successor,kind in self.after[node]:
                    if successor not in forward:forward.add(successor);todo.append(successor)
        nodes=backward|forward
        todo=list(forward)
        while todo:
            node=todo.pop()
            for predecessor,kind in self.before[node]:
                if predecessor not in nodes:nodes.add(predecessor);todo.append(predecessor)
        context=set()
        for node in nodes:
            if node in self.events and self.events[node]['kind']!='action':
                event=self.events[node];context.add(event['action'])
                if event['execution'] in self.events:context.add(event['execution'])
        context-=nodes;nodes.update(context)
        if direction=='both':
            # An action groups the recorded and replay observations. Keep that
            # context without claiming one source-level call produced the
            # entire command's output.
            actions=[node for node in nodes if node in self.events and self.events[node]['kind']=='action']
            for action in actions:
                nodes.update(material for material,kind in self.after[action]
                             if kind in {'recorded_observation','replay_observation'})
        return {'events':sorted(n for n in nodes if n in self.events),
                'materials':sorted(n for n in nodes if n in self.materials),
                'context_events':sorted(context),
                'edges':[[a,b,k] for a in sorted(nodes) for b,k in self.after[a] if b in nodes]}
