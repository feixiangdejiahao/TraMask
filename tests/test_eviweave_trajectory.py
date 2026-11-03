"""Real commands, file versions, pipes and version-qualified program slicing."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from eviweave.artifacts import read_json,write_json
from eviweave.blobs import BlobStore
from eviweave.trace_guest import execute
from eviweave.trajectory import Trajectory,TrajectoryGraph,read_trace
from eviweave.slicing import slice_location


def recorded(tmp_path,sources,command,*,timeout=20):
    root=tmp_path/'repo';root.mkdir();out=tmp_path/'collected';out.mkdir();BlobStore(out/'blobs').create()
    rows=[]
    for name,code in sources.items():
        p=root/name;p.parent.mkdir(parents=True,exist_ok=True);raw=code.encode();p.write_bytes(raw)
        digest=BlobStore(out/'blobs').put(raw)
        rows.append({'kind':'file','path':'/app/'+name,'sha256':digest})
    subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Research','-c','user.email=research@example.invalid','commit','--allow-empty','-qm','initial'],check=True)
    graph=Trajectory(out);graph.start({'files':rows})
    call=tmp_path/'calls'/'s1';call.mkdir(parents=True)
    (call/'command.sh').write_text(command);write_json(call/'archived_expected.json',{'output':'original-output'})
    result=execute({'root':str(root),'workdir':str(root),'command':command,'env':{},'output':str(call/'output.bin'),
                    'trace_directory':str(call/'trace'),'timeout':timeout},BlobStore)
    result['trace']=str(call/'trace');graph.add_action({'id':'s1','command':command,'expected':{'output':'original-output'}},result,read_trace(result))
    final=[]
    for p in root.rglob('*'):
        if p.is_file() and '.git' not in p.parts and '__pycache__' not in p.parts:
            raw=p.read_bytes();digest=BlobStore(out/'blobs').put(raw)
            final.append({'kind':'file','path':'/app/'+str(p.relative_to(root)),'sha256':digest})
    graph.finish({'files':final});write_json(out/'manifest.json',{'replay':str(out),'trajectory':str(out/'trajectory.json')})
    return root,out,result


def source_ref(out,path,needle):
    graph=TrajectoryGraph(out/'trajectory.json')
    for identity,m in graph.materials.items():
        if m['kind']=='file' and m['path']==path:
            raw=BlobStore(out/'blobs').read(m['sha256'])
            if needle.encode() in raw and graph.consumers(path,m['sha256']):
                a=raw.index(needle.encode());return str(out/'trajectory.json')+'#/materials/'+identity,a,a+len(needle.encode())
    raise AssertionError(path)


def rendered(out,view):
    graph=read_json(out/'trajectory.json');return '\n'.join(
        BlobStore(out/'blobs').read(graph['materials'][f['material']]['sha256'])[a:b].decode()
        for f in view['files'] for a,b in f['ranges'])


def test_same_command_append_run_delete_and_pipeline_keep_actual_bytes(tmp_path):
    command="printf 'x = 3\n' >gone.py; printf 'print(x + 1)\n' >>gone.py; python3 gone.py | tr 4 5; rm gone.py"
    root,out,result=recorded(tmp_path,{},command)
    assert result['returncode']==0 and not (root/'gone.py').exists()
    graph=TrajectoryGraph(out/'trajectory.json')
    assert '/app/gone.py' not in graph.data['submitted']
    source,a,b=source_ref(out,'/app/gone.py','print(x + 1)')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert 'x = 3' in rendered(out,view)
    edges=view['trajectory']['edges']
    assert any(kind=='retained_bytes' for x,y,kind in edges)
    assert any(kind=='stream_transfer' for x,y,kind in edges)
    assert any(graph.events[e]['kind']=='stream_write' and BlobStore(out/'blobs').read(graph.events[e]['data'])==b'5\n' for e in view['trajectory']['events'])


def test_cross_file_global_state_and_helper_caller_are_in_one_view(tmp_path):
    sources={'state.py':'value = 0\ndef reset():\n    global value\n    value = 7\ndef read():\n    return value\n',
             'check.py':'from state import reset, read\nreset()\nresult = read()\nassert result == 7\nprint(result)\n'}
    root,out,result=recorded(tmp_path,sources,'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','read()')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'value = 7' in text and 'global value' in text and 'assert result == 7' in text
    assert view['state_dependencies']
    source,a,b=source_ref(out,'/app/state.py','return value')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert 'assert result == 7' in rendered(out,view)
    assert len(view['entries'])>=2


def test_recursive_helper_summaries_reach_a_fixed_point(tmp_path):
    sources={'state.py':'''value = 0
def first(n):
    if n:
        second(n - 1)
    else:
        global value
        value = 7
def second(n):
    first(n)
def read():
    return value
''','check.py':'from state import first, read\nfirst(3)\nassert read() == 7\n'}
    _,out,result=recorded(tmp_path,sources,'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','read()')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'first(3)' in text and 'value = 7' in text and 'assert read() == 7' in text
    assert view['state_dependencies']


def test_deleted_file_execution_uses_old_implementation_not_final_version(tmp_path):
    old='def operation(x):\n    return x + 1\n';new='def operation(x):\n    return x + 2\n'
    script='from impl import operation\nassert operation(3) == 4\nprint("old-pass")\n'
    command="python3 check.py; printf 'def operation(x):\\n    return x + 2\\n' >impl.py; rm check.py"
    root,out,result=recorded(tmp_path,{'impl.py':old,'check.py':script},command)
    assert result['returncode']==0 and (root/'impl.py').read_text()==new
    source,a,b=source_ref(out,'/app/check.py','operation(3)')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'return x + 1' in text and 'return x + 2' not in text
    graph=TrajectoryGraph(out/'trajectory.json');final=graph.materials[graph.data['submitted']['/app/impl.py']]
    assert final['sha256']==hashlib.sha256(new.encode()).hexdigest()


def test_inline_and_stdin_programs_are_real_searchable_code_inputs(tmp_path):
    _,out,result=recorded(tmp_path,{},"printf 'print(3 + 4)\\n' | python3 -; python3 -c 'print(8 + 1)'")
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json');inputs=[m for m in graph.materials.values() if m['kind']=='code_input']
    code={BlobStore(out/'blobs').read(m['sha256']) for m in inputs}
    assert b'print(3 + 4)\n' in code and b'print(8 + 1)' in code
    assert any(k=='concatenates' for a,b,k in graph.data['edges'])


def test_implicit_interpreter_stdin_and_module_data_stdin_have_distinct_roles(tmp_path):
    command="python3 <<'PY'\nprint('implicit-source')\nPY\nprintf 'payload-data\\n' | python3 -m consumer -"
    _,out,result=recorded(tmp_path,{'consumer.py':'import sys\nprint(sys.stdin.read())\n'},command)
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    code=[BlobStore(out/'blobs').read(m['sha256']) for m in graph.materials.values() if m['kind']=='code_input']
    assert b"print('implicit-source')\n" in code and b'payload-data\n' not in code


def test_parent_validation_keeps_child_file_effects_without_reading_child_output(tmp_path):
    sources={'parent.py':'import subprocess\nsubprocess.run(["python3", "child.py"], check=True)\n',
             'child.py':'from pathlib import Path\nPath("result.json").write_text("{\\"value\\":7}")\n'}
    _,out,result=recorded(tmp_path,sources,'python3 parent.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/parent.py','subprocess.run')
    view,=slice_location(out/'manifest.json',source,a,b)
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(graph.materials[m]['path']=='/app/result.json' for m in view['trajectory']['materials'])


def test_module_analyzer_input_keeps_comments_as_data_and_implementation_as_code(tmp_path):
    sources={'bandit.py':'from pathlib import Path\nimport sys\nprint(Path(sys.argv[1]).read_text())\n',
             'input.py':'value = 3\n# nosec-begin\n'}
    _,out,result=recorded(tmp_path,sources,'python3 -m bandit input.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/input.py','value = 3')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert view['mode']=='source_input'
    source,a,b=source_ref(out,'/app/bandit.py','print(')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert view['mode']=='program'


def test_failed_attempt_and_outputs_are_retained(tmp_path):
    _,out,result=recorded(tmp_path,{'bad.py':'raise RuntimeError("trial-failed")\n'},'python3 bad.py')
    assert result['returncode']!=0
    graph=TrajectoryGraph(out/'trajectory.json');source,a,b=source_ref(out,'/app/bad.py','RuntimeError')
    views=slice_location(out/'manifest.json',source,a,b)
    assert views and any(v['kind']=='exit' and v['returncode']!=0 for v in graph.events.values())
    assert graph.events['s1']['original']!=graph.events['s1']['replay_output']


def test_timeout_reaps_real_process_exits_and_keeps_the_trace(tmp_path):
    _,out,result=recorded(tmp_path,{},"python3 -c 'import os\nwhile True: os.getpid()'",timeout=0.1)
    assert result['timed_out'] and result['returncode']==-1
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(e['kind']=='exit' and e['returncode']<0 for e in graph.events.values())


def test_exec_from_non_leader_thread_uses_that_threads_arguments(tmp_path):
    code='''#include <pthread.h>
#include <unistd.h>
void *run(void *ignored) {
    execlp("echo", "echo", "thread-exec", (char *)0);
    _exit(1);
}
int main(void) {
    pthread_t thread;
    pthread_create(&thread, 0, run, 0);
    for (;;) pause();
}
'''
    _,out,result=recorded(tmp_path,{'thread.c':code},'cc -pthread thread.c -o thread && ./thread')
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(e['kind']=='exec' and e['argv']==['echo','thread-exec'] for e in graph.events.values())


def test_proc_input_is_recorded_as_observed_data_not_a_disk_snapshot(tmp_path):
    _,out,result=recorded(tmp_path,{},'cat /proc/sys/kernel/pid_max')
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(e['kind']=='stream_read' and e['channel']=='/proc/sys/kernel/pid_max' for e in graph.events.values())
    assert all(m['kind']!='file' or not m['path'].startswith('/proc/') for m in graph.materials.values())


def test_process_input_prefix_keeps_prior_inputs_with_linear_edges(tmp_path):
    code='''from pathlib import Path
for i in range(60):
    value = Path('input.txt').read_text()
    Path('output.txt').write_text(value + str(i))
'''
    _,out,result=recorded(tmp_path,{'check.py':code,'input.txt':'condition-'},'python3 check.py')
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    outputs=[(e,v) for e,v in graph.events.items() if v['kind']=='write' and graph.materials[v['material']]['path']=='/app/output.txt']
    last,write=outputs[-1];closure=graph.slice([write['material']],direction='backward')
    reads=[e for e,v in graph.events.items() if v['kind']=='read' and graph.materials[v['material']]['path']=='/app/input.txt']
    assert len(reads)==60 and set(reads)<=set(closure['events'])
    assert not any(graph.events[e]['kind']=='read' and graph.events[e]['ordinal']>write['ordinal'] for e in closure['events'])
    edges=[e for e in graph.data['edges'] if e[2] in {'input_prefix','process_may_depend'}]
    assert len(edges)<=len(graph.events)


def test_shared_helper_does_not_join_an_independent_execution(tmp_path):
    sources={'helper.py':'def value():\n    return 7\n',
             'first.py':'from helper import value\nassert value() == 7\n',
             'other.py':'from helper import value\nfrom pathlib import Path\nPath("unrelated.txt").write_text(str(value()))\n'}
    _,out,result=recorded(tmp_path,sources,'PYTHONDONTWRITEBYTECODE=1 python3 first.py; PYTHONDONTWRITEBYTECODE=1 python3 other.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/first.py','value()')
    view,=slice_location(out/'manifest.json',source,a,b)
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(f['path']=='/app/helper.py' for f in view['files'])
    assert all(graph.materials[m]['path']!='/app/unrelated.txt' for m in view['trajectory']['materials'])


def test_repeated_blob_bytes_share_storage_after_collection(tmp_path):
    _,out,result=recorded(tmp_path,{'check.py':'print(7)\n'},'python3 check.py; python3 check.py')
    assert result['returncode']==0
    trace_store=BlobStore(Path(result['trace'])/'blobs')
    for blob in trace_store.directory.iterdir():
        if blob.is_file():
            assert trace_store.read(blob.name)==BlobStore(out/'blobs').read(blob.name)


def test_slice_cli_accepts_an_exported_relative_source_with_explicit_base(tmp_path):
    import os
    _,out,result=recorded(tmp_path,{'check.py':'value = 3\nassert value == 3\n'},'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','value == 3')
    export=tmp_path/'export';export.mkdir()
    filename,separator,fragment=source.partition('#')
    relative=os.path.relpath(filename,export)+separator+fragment
    destination=tmp_path/'slice'
    subprocess.run([sys.executable,'-m','eviweave','slice','--manifest',str(out/'manifest.json'),
                    '--source',relative,'--source-base',str(export),'--start',str(a),'--end',str(b),
                    '--out',str(destination)],cwd=Path(__file__).resolve().parents[1]/'src',check=True,capture_output=True)
    assert read_json(destination/'slice.json')


def test_observer_artifacts_do_not_become_subject_file_versions(tmp_path):
    _,out,result=recorded(tmp_path,{},'cat ../calls/s1/command.sh')
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(e['kind']=='observer_artifact_access' for e in graph.events.values())
    assert all(m['kind']!='file' or not m['path'].endswith('/calls/s1/command.sh') for m in graph.materials.values())


def test_lazy_episode_recovers_the_same_slice_without_losing_inputs(tmp_path):
    from eviweave.slicing import TrajectorySlicer
    _,out,result=recorded(tmp_path,{'check.py':'value = 3\nassert value == 3\n'},'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','value == 3')
    slicer=TrajectorySlicer(out/'manifest.json')
    lazy,=slicer.location(source,a,b,expand_trajectory=False)
    expanded,=slicer.location(source,a,b)
    criterion=lazy['trajectory_criterion']
    assert expanded['trajectory']==slicer.trajectory.slice(criterion['seeds'],inputs=criterion['inputs'])
    assert lazy['files']==expanded['files']


def test_cached_program_view_keeps_each_selected_read_event(tmp_path):
    from eviweave.slicing import TrajectorySlicer
    code='value = 3\nassert value == 3\n'
    _,out,result=recorded(tmp_path,{'body.py':code},'python3 -c \'from pathlib import Path; exec(Path("body.py").read_text()); exec(Path("body.py").read_text())\'')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/body.py','value == 3');slicer=TrajectorySlicer(out/'manifest.json')
    path,digest,_=slicer.source(source);events=slicer.trajectory.consumers(path,digest)
    assert len(events)==2
    for event in events:
        view,=slicer.location(source,a,b,consumer=event,expand_trajectory=False)
        assert view['trajectory_criterion']['seeds']==[event]


def test_unexecuted_source_slice_keeps_its_graph_for_later_matching(tmp_path):
    from eviweave.slicing import TrajectorySlicer
    code='first = 3\nsecond = first + 1\nassert second == 4\n'
    _,out,result=recorded(tmp_path,{'unused.py':code},'printf done')
    assert result['returncode']==0
    slicer=TrajectorySlicer(out/'manifest.json');identity=next(m for m,v in slicer.trajectory.materials.items() if v['path']=='/app/unused.py')
    source=str(out/'trajectory.json')+'#/materials/'+identity
    a=code.index('second == 4');view,=slicer.location(source,a,a+len('second == 4'),expand_trajectory=False)
    path,digest,_=slicer.source(source);nodes=slicer.cache[path,digest].export_nodes()
    assert view['execution'] is None and view['static_slice']['nodes']
    assert set(view['static_slice']['nodes'])<={n['id'] for n in nodes}


def test_before_each_setup_is_joined_with_its_test(tmp_path):
    code='''let setup;
function beforeEach(fn) { setup = fn; }
function describe(name,fn) { fn(); }
function it(name,fn) { setup(); fn(); }
function finish(runner) { runner.done = true; }
function expect(value) { return {toBe(expected) { if (value !== expected) throw Error('wrong'); }}; }
describe('suite', () => {
  let runner;
  beforeEach(() => { runner = {done:false}; });
  it('case', () => { finish(runner); expect(runner.done).toBe(true); });
});
'''
    _,out,result=recorded(tmp_path,{'check.js':code},'node check.js')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.js','finish(runner)')
    # The first occurrence is a declaration; select the invocation instead.
    a=code.index('finish(runner);');b=a+len('finish(runner)')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'runner = {done:false}' in text and 'expect(runner.done)' in text


def test_unittest_setup_and_bound_method_arguments_are_connected(tmp_path):
    code='''import unittest
class TestState(unittest.TestCase):
    def setUp(self):
        self.values = []
    def add(self, value):
        self.values.append(value)
    def test_state(self):
        self.add(3)
        self.assertEqual(self.values, [3])
unittest.main()
'''
    _,out,result=recorded(tmp_path,{'check.py':code},'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','self.add(3)')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'self.values = []' in text and 'self.values.append(value)' in text and 'self.assertEqual' in text
    call,=[c for c in view['calls'] if c['kind']=='bound_method']
    assert call['bound_receiver']=='self' and call['arguments'][0]['parameter']=='value'
    assert any(c['kind']=='framework_setup' for c in view['calls'])


def test_literal_embedded_program_gets_its_own_dependency_slices(tmp_path):
    code='value = eval("sum([1, 2, 3])")\nassert value == 6\n'
    _,out,result=recorded(tmp_path,{'check.py':code},'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','eval("sum([1, 2, 3])")')
    view,=slice_location(out/'manifest.json',source,a,b)
    embedded,=view['embedded_inputs']
    assert embedded['language']=='.py' and embedded['text']=='sum([1, 2, 3])'
    assert embedded['graph'] and embedded['slices']


def test_snapshot_reader_binds_generated_version_not_final_overwrite(tmp_path):
    code='''import json
from pathlib import Path
Path('state.json').write_text('{"duration":304}')
print(json.loads(Path('state.json').read_text())['duration'])
Path('state.json').write_text('{"duration":999}')
'''
    _,out,result=recorded(tmp_path,{'check.py':code},'python3 check.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/state.json','304')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert view['structure']=={'duration':304}
    graph=TrajectoryGraph(out/'trajectory.json');material=graph.materials[view['material']]
    assert material['producer'] is not None
    assert graph.data['submitted']['/app/state.json']!=view['material']


def test_kernel_file_copy_preserves_source_provenance(tmp_path):
    _,out,result=recorded(tmp_path,{'original.py':'print(42)\n'},'cp original.py copied.py; python3 copied.py; rm copied.py')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/copied.py','print(42)')
    view,=slice_location(out/'manifest.json',source,a,b)
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(graph.materials[m]['path']=='/app/original.py' for m in view['trajectory']['materials'])


def test_bytecode_lineage_does_not_bind_a_cached_import_to_new_source(tmp_path):
    old='def operation(x):\n    return x + 1\n'
    check='from impl import operation\nassert operation(3) == 4\nprint("cached-old")\n'
    edit="import os; from pathlib import Path; p=Path('impl.py'); t=p.stat().st_mtime_ns; p.write_text('def operation(x):\\n    return x + 2\\n'); os.utime(p,ns=(t,t))"
    import shlex
    command='python3 -c "import impl"; python3 -c '+shlex.quote(edit)+'; python3 check.py'
    _,out,result=recorded(tmp_path,{'impl.py':old,'check.py':check},command)
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.py','operation(3)')
    view,=slice_location(out/'manifest.json',source,a,b)
    text=rendered(out,view)
    assert 'return x + 1' in text and 'return x + 2' not in text
    graph=TrajectoryGraph(out/'trajectory.json');physical=graph.state_at(view['execution'])['/app/impl.py']
    assert b'return x + 2' in BlobStore(out/'blobs').read(graph.materials[physical]['sha256'])


def test_read_after_equal_length_rewrite_with_restored_mtime_binds_new_bytes(tmp_path):
    import shlex
    program=('import os; from pathlib import Path; p=Path("state.txt"); '
             's=p.stat(); p.read_bytes(); p.write_bytes(b"bbbb"); '
             'os.utime(p,ns=(s.st_atime_ns,s.st_mtime_ns)); p.read_bytes()')
    _,out,result=recorded(tmp_path,{'state.txt':'aaaa'},'python3 -c '+shlex.quote(program))
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json');store=BlobStore(out/'blobs')
    reads=[e for e in graph.events.values() if e['kind']=='read' and
           graph.materials[e['material']]['path']=='/app/state.txt' and store.read(e['data'])==b'bbbb']
    assert reads and all(graph.materials[e['material']]['sha256']==hashlib.sha256(b'bbbb').hexdigest()
                         and e['binding']=='matches_read_bytes' for e in reads)


def test_observed_memfd_write_invalidates_cached_version(tmp_path):
    import ctypes,os
    from eviweave.trace_guest import Recorder
    fd=os.memfd_create('eviweave');old=b'old-version\n';new=b'new-version\n'
    try:
        os.write(fd,old);state=os.fstat(fd);pid=os.getpid()
        recorder=Recorder({'root':str(tmp_path),'trace_directory':str(tmp_path/'trace'),
                           'output':str(tmp_path/'output')},BlobStore)
        recorder.activities[pid]=1
        assert recorder.fd(pid,fd)['version']['sha256']==hashlib.sha256(old).hexdigest()
        data=ctypes.create_string_buffer(new)
        recorder.enter(pid,18,(fd,ctypes.addressof(data),len(new),0,0,0))
        count=os.pwrite(fd,new,0)
        os.utime(fd,ns=(state.st_atime_ns,state.st_mtime_ns))
        recorder.leave(pid,count)
        assert recorder.fd(pid,fd)['version']['sha256']==hashlib.sha256(new).hexdigest()
        recorder.log.close()
    finally:os.close(fd)


def test_shared_mapping_upgraded_to_writable_keeps_updated_file_bytes(tmp_path):
    import shlex
    program='''import ctypes,os
libc=ctypes.CDLL(None)
libc.mmap.restype=ctypes.c_void_p
fd=os.open("state.txt",os.O_RDWR)
assert os.pread(fd,4,0)==b"aaaa"
address=libc.mmap(None,4,1,1,fd,0)
assert libc.mprotect(ctypes.c_void_p(address),4,3)==0
ctypes.memmove(address,b"bbbb",4)
assert os.pread(fd,4,0)==b"bbbb"
assert libc.munmap(ctypes.c_void_p(address),4)==0
os.close(fd)
'''
    _,out,result=recorded(tmp_path,{'state.txt':'aaaa'},'python3 -c '+shlex.quote(program))
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json');store=BlobStore(out/'blobs')
    reads=[e for e in graph.events.values() if e['kind']=='read' and
           graph.materials[e['material']]['path']=='/app/state.txt' and store.read(e['data'])==b'bbbb']
    assert reads and all(graph.materials[e['material']]['sha256']==hashlib.sha256(b'bbbb').hexdigest()
                         and e['binding']=='matches_read_bytes' for e in reads)


def test_original_observation_is_not_bound_as_a_replay_output(tmp_path):
    _,out,result=recorded(tmp_path,{'check.py':'print("replayed-value")\n'},'python3 check.py')
    graph=TrajectoryGraph(out/'trajectory.json')
    original=graph.events['s1']['original']+'#/output'
    view,=slice_location(out/'manifest.json',original,0,len('original-output'))
    assert view['origin']=='original'
    assert view['trajectory']['events']==['s1']
    replay=graph.events['s1']['replay_output']
    view,=slice_location(out/'manifest.json',replay,0,len('replayed-value'))
    assert view['origin']=='replay'
    assert any(graph.events[e]['kind']=='stream_write' for e in view['trajectory']['events'])


def test_redirected_background_job_does_not_turn_success_into_timeout(tmp_path):
    import os,signal
    _,out,result=recorded(tmp_path,{},'sleep 10 >/dev/null 2>&1 & printf done')
    assert result['returncode']==0 and result['elapsed_seconds']<2
    graph=TrajectoryGraph(out/'trajectory.json')
    detached=[e for e in graph.events.values() if e['kind']=='unresolved_background_process']
    assert detached
    for e in detached:
        try:os.kill(e['pid'],signal.SIGKILL)
        except ProcessLookupError:pass


def test_import_alias_and_keyword_arguments_keep_parameter_correspondence(tmp_path):
    sources={'helper.py':'def pair(z, a):\n    return z + a\n',
             'check.py':'from helper import pair as combine\nvalue = combine(a=5, z=2)\nassert value == 7\n'}
    _,out,result=recorded(tmp_path,sources,'python3 check.py');assert result['returncode']==0
    source,a,b=source_ref(out,'/app/helper.py','return z + a')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert 'assert value == 7' in rendered(out,view)
    call=next(c for c in view['calls'] if c['parameters']==['z','a'])
    assert [a['parameter'] for a in call['arguments']]==['a','z']


def test_named_pytest_fixture_is_connected_to_test_parameter(tmp_path):
    code='''import pytest
@pytest.fixture
def prepared():
    return [7]
def test_value(prepared):
    actual = sum(prepared)
    assert actual == 7
'''
    import shlex
    _,out,result=recorded(tmp_path,{'test_value.py':code},shlex.join([sys.executable,'-m','pytest','-q','test_value.py']))
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/test_value.py','sum(prepared)')
    view,=slice_location(out/'manifest.json',source,a,b)
    assert 'return [7]' in rendered(out,view)
    assert any(c.get('provided_parameter')=='prepared' for c in view['calls'])


def test_compiled_binary_output_remains_connected_to_its_source(tmp_path):
    code='#include <stdio.h>\nint main(void) { puts("compiled-proof"); return 0; }\n'
    _,out,result=recorded(tmp_path,{'check.c':code},'cc check.c -o check; ./check; rm check')
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/check.c','compiled-proof')
    views=slice_location(out/'manifest.json',source,a,b)
    graph=TrajectoryGraph(out/'trajectory.json')
    assert any(graph.events[e]['kind']=='stream_write' and
               b'compiled-proof' in BlobStore(out/'blobs').read(graph.events[e]['data'])
               for v in views for e in v['trajectory']['events'])


def test_full_overwrite_does_not_make_old_bytes_a_data_dependency(tmp_path):
    _,out,result=recorded(tmp_path,{'state.txt':'old-value\n'},"printf 'new-value\\n' > state.txt; cat state.txt")
    assert result['returncode']==0
    source,a,b=source_ref(out,'/app/state.txt','new-value')
    view,=slice_location(out/'manifest.json',source,a,b)
    graph=TrajectoryGraph(out/'trajectory.json');old=hashlib.sha256(b'old-value\n').hexdigest()
    assert all(graph.materials[m]['sha256']!=old for m in view['trajectory']['materials'])


def test_pytest_cache_verification_selects_matching_saved_source(tmp_path):
    import base64,shlex
    from eviweave.python_cache_guest import verify
    code='def test_value():\n    actual = 3\n    assert actual == 3\n'
    bad=code.replace('actual == 3','actual == 4')
    _,out,result=recorded(tmp_path,{'test_value.py':code},shlex.join([sys.executable,'-m','pytest','-q','test_value.py']))
    assert result['returncode']==0
    graph=TrajectoryGraph(out/'trajectory.json')
    cache=next(v for v in graph.materials.values() if v['kind']=='file' and v['path'].endswith('.pyc') and 'test_value' in v['path'])
    old=hashlib.sha256(code.encode()).hexdigest();new=hashlib.sha256(bad.encode()).hexdigest()
    proof=verify({'blobs':str(out/'blobs'),'sources':{old:base64.b64encode(code.encode()).decode(),new:base64.b64encode(bad.encode()).decode()},
                  'entries':[{'event':'cache','cache':cache['sha256'],'sources':[old,new],'rewrite':True,'optimize':0}]},BlobStore)
    assert proof['cache']['matched_sources']==[old]


def test_optimized_bytecode_verification_uses_the_cache_optimization_level(tmp_path):
    import base64,py_compile
    from eviweave.python_cache_guest import verify
    source=tmp_path/'old.py';code=b'def value():\n    assert False\n    return 7\n';source.write_bytes(code)
    cache=Path(py_compile.compile(str(source),optimize=1,doraise=True)).read_bytes()
    store=BlobStore(tmp_path/'blobs');store.create();cache_id=store.put(cache)
    code_id=hashlib.sha256(code).hexdigest()
    proof=verify({'blobs':str(store.directory),'sources':{code_id:base64.b64encode(code).decode()},
                  'entries':[{'event':'cache','cache':cache_id,'sources':[code_id],'rewrite':False,'optimize':1}]},BlobStore)
    assert proof['cache']['matched_sources']==[code_id]
