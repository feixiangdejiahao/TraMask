"""Replay every recorded shell action up to submission, with a state-only gate.

This is a separate revision. It never rewrites the original pilot's artifacts
or its selected historical test contexts, and never calls a language model.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import time

from .corpus import RUN, calls, read, receipt, write
from .runtime import Container


OUTPUT = RUN / "submission_state_audit" / "full_replay_v01"
SENTINEL = "echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
ENV = {"PAGER": "cat", "MANPAGER": "cat", "LESS": "-R",
       "PIP_PROGRESS_BAR": "off", "TQDM_DISABLE": "1"}


def state_directory(case_id):
    """Resolve an explicitly verified state correction, preserving earlier runs."""
    path = RUN / 'submission_state_audit/active_state_overrides.json'
    overrides = read(path) if path.exists() else {}
    entry = overrides.get('cases', {}).get(case_id)
    if not entry:
        return OUTPUT / case_id
    directory = Path(entry['directory']).resolve()
    if not directory.is_relative_to((RUN / 'submission_state_audit').resolve()):
        raise ValueError('State override outside the audit evidence directory')
    for key in ('summary', 'validation'):
        if receipt(entry[key]['path']) != entry[key]:
            raise ValueError('State override receipt changed: ' + case_id + '/' + key)
    return directory

# Matches minisweagent.environments.local._run in the original version 2.4.5.
# No shell text reaches the host shell. A timeout kills this action's process
# group; it must not restart the container or kill unrelated background jobs.
EXECUTE = r'''
import hashlib,json,os,signal,subprocess,sys,time
r=json.load(sys.stdin)
t=time.monotonic()
timed_out=False;output_drain_incomplete=False;exception_info='';returncode=-1
try:
    p=subprocess.Popen(r['command'],shell=True,text=True,cwd='/app',
        env=os.environ | r['env'],encoding='utf-8',errors='replace',
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
    try:
        output,_=p.communicate(timeout=30)
    except subprocess.TimeoutExpired as expired:
        timed_out=True
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:
            output,_=p.communicate(timeout=5)
        except subprocess.TimeoutExpired as drain:
            # A child in its own process group can retain the output pipe after
            # the action shell is killed. Do not kill unrelated groups or wait
            # forever for EOF; keep the received bytes and record the boundary.
            output=drain.output or expired.output or ''
            if isinstance(output,bytes):output=output.decode('utf-8','replace')
            output_drain_incomplete=True
            if p.stdout:p.stdout.close()
            try:p.wait(timeout=1)
            except subprocess.TimeoutExpired:pass
        raise subprocess.TimeoutExpired(r['command'],30,output=output)
    returncode=p.returncode
except Exception as e:
    output=getattr(e,'output',None) or ''
    if isinstance(output,bytes):output=output.decode('utf-8',errors='replace')
    exception_info=str(e)
raw=output.encode('utf-8')
open(r['output'],'wb').write(raw)
print(json.dumps({'returncode':returncode,'exception_info':exception_info,
    'timed_out':timed_out,'elapsed_seconds':time.monotonic()-t,
    'output_drain_incomplete':output_drain_incomplete,
    'output_bytes':len(raw),'output_sha256':hashlib.sha256(raw).hexdigest()}))
'''

# Contents of all application and temporary files are inventoried, including
# ignored tests, node_modules, builds and caches. This is a receipt of the new
# replay state, not an independent original-state oracle for untracked files.
INVENTORY = r'''
import hashlib,json,os,stat,sys
r=json.load(sys.stdin)
rows=[];errors=[]
for root in ['/app','/tmp']:
    for directory,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if os.path.join(directory,d) not in ['/app/.git',r['scratch']])
        symlinks=[d for d in dirs if os.path.islink(os.path.join(directory,d))]
        for name in sorted(files+symlinks):
            path=os.path.join(directory,name)
            try:
                st=os.lstat(path);row={'path':path,'mode':stat.S_IMODE(st.st_mode)}
                if stat.S_ISLNK(st.st_mode):row.update(kind='symlink',target=os.readlink(path))
                elif stat.S_ISREG(st.st_mode):
                    h=hashlib.sha256()
                    with open(path,'rb') as f:
                        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
                    row.update(kind='file',bytes=st.st_size,sha256=h.hexdigest())
                else:row.update(kind='special',stat_mode=st.st_mode)
                rows.append(row)
            except OSError as e:errors.append({'path':path,'error':str(e)})
json.dump({'roots':['/app','/tmp'],'excluded':['/app/.git',r['scratch']],
    'files':rows,'errors':errors},open(r['destination'],'w'),indent=2)
print(json.dumps({'files':len(rows),'errors':len(errors)}))
'''


def submission_actions(document):
    actions = calls(document)
    markers = [i for i, a in enumerate(actions) if a['command'].strip() == SENTINEL]
    if len(markers) != 1 or markers[0] != len(actions) - 1:
        raise ValueError("Require exactly one separate terminal submission marker")
    if any(a['function'] != 'bash' for a in actions):
        raise ValueError("Unsupported trajectory tool")
    return actions[:-1], actions[-1]


def execute_action(runtime, action):
    directory = runtime.output / 'calls' / action['id']
    directory.mkdir(parents=True, exist_ok=False)
    (directory / 'command.sh').write_text(action['command'])
    write(directory / 'archived_expected.json', action['expected'])
    remote = runtime.scratch + '/' + action['id'] + '.output'
    request = {'command': action['command'], 'env': ENV, 'output': remote}
    raw = runtime._control(['python3', '-c', EXECUTE], timeout=60,
                           input_bytes=json.dumps(request).encode())
    result = json.loads(raw.stdout)
    runtime.copy_from(remote, directory / 'output.bin')
    result.update(id=action['id'], command_sha256=receipt(directory / 'command.sh')['sha256'],
                  shell='/bin/sh', timeout_seconds=30, working_directory='/app',
                  original_returncode=(action['expected'] or {}).get('returncode'),
                  output_compared=False)
    write(directory / 'result.json', result)
    runtime.records.append(result)
    runtime._persist()
    return result


def replay_submission(case, *, output=OUTPUT):
    from .submission_state import validate_submission_state
    out = Path(output) / case['id']
    if (out / 'summary.json').exists():
        return read(out / 'summary.json')
    source = RUN / 'inputs' / case['id']
    actions, marker = submission_actions(read(source / 'trajectory.json'))
    write(out / 'plan.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'case': case,
        'trajectory': receipt(source / 'trajectory.json'),
        'model_patch': receipt(source / 'model.patch'),
        'terminal_marker': marker['id'], 'action_count': len(actions),
        'strategy': 'all recorded commands in order; no selected-test cutoff or patch transplant',
        'acceptance': 'independent comparison with base + submitted patch, never stdout equality',
        'shell': '/bin/sh', 'timeout_seconds': 30, 'timeout_cleanup': 'SIGKILL action process group',
        'environment_overlay': ENV,
        'environment_limit': 'ATIF lacks original environment overrides; use verified mini-swe-agent 2.4.5 defaults',
        'elapsed_between_actions': 'literal recorded sleeps only; original model thinking delays unavailable',
        'code': [receipt(Path(__file__)), receipt(Path(__file__).with_name('submission_state.py'))],
    })
    records = []
    with Container(case['image'], out / 'runtime', case['base_commit']) as runtime:
        for i, action in enumerate(actions):
            write(out / 'progress.json', {'id':case['id'],'completed':i,'total':len(actions),'executing':action['id']})
            records.append(execute_action(runtime, action))
        write(out / 'progress.json', {'id':case['id'],'completed':len(actions),'total':len(actions),'executing':'freeze_submission_state'})
        # Freeze before validation helpers create files. A commit captures the
        # filesystem, not live processes; process inventory is retained too.
        processes = runtime._control(['ps','-eo','pid,ppid,pgid,args'], check=False)
        (out / 'processes.txt').write_bytes(processes.stdout)
        checkpoint = runtime.checkpoint('before_submission')
        changed = runtime._docker(['diff', runtime.name],timeout=60)
        (out / 'docker_diff.txt').write_bytes(changed.stdout)
        replay_image = runtime.image_id
        original_scratch = runtime.scratch
    # Validate the frozen checkpoint, not the live process state which could
    # still be changing due to recorded background jobs.
    with Container(checkpoint['image_id'], out / 'frozen_state', checkpoint['head']) as frozen:
        remote = original_scratch + '/submission_inventory.json'
        frozen._control(['python3','-c',INVENTORY],timeout=600,
                         input_bytes=json.dumps({'scratch':original_scratch,'destination':remote}).encode())
        frozen.copy_from(remote,out / 'filesystem_inventory.json')
        validation = validate_submission_state(frozen,source / 'model.patch',out / 'validation',base_commit=case['base_commit'])
        result = {'id':case['id'],'actions_executed':len(records),'terminal_marker':marker['id'],
            'image_id':replay_image,'checkpoint':checkpoint,
            'validation':validation,'output_equality_used':False,
            'timeouts':[r['id'] for r in records if r['timed_out']],
            'returncode_differences':[r['id'] for r in records if r['original_returncode'] is not None and r['returncode']!=r['original_returncode']],
            'inventory':receipt(out / 'filesystem_inventory.json'),
            'scope':'Full chronological reconstruction. Submitted tracked tree independently checked; untracked/tmp/dependencies preserved but no original final filesystem manifest exists for byte equality.',
        }
        write(out / 'summary.json',result)
        return result
