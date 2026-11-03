"""Step A: collect test versions and execution associations during replay."""
from __future__ import annotations

import base64
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil

from .artifacts import read_json, write_json
from .blobs import BlobStore
from .invocations import commands, in_scope, named_results, result_matches, result_notices, source_may_change_during_action
from .test_units import discover


SNAPSHOT_SCRIPT = Path(__file__).with_name('snapshot_runner.py').read_text()
BLOB_SCRIPT = Path(__file__).with_name('blobs.py').read_text()


def collect_tests(case, input_directory, out, *, shared_chunks=None):
    from .replay import replay_case
    return replay_case(case, input_directory, out, observer_factory=lambda actions, inputs, case:
                       ReplayTrajectoryCollector(Path(out) / 'tests', actions, shared_chunks=shared_chunks))


class ReplayTestCollector:
    """Observer hooks do not change shell text, inject reporters, or run tests."""
    trace_commands=False

    def __init__(self, out, actions, *, shared_chunks=None):
        self.out = Path(out).resolve()
        self.out.mkdir(parents=True, exist_ok=False)
        self.store = BlobStore(self.out / 'blobs')
        if shared_chunks is not None:
            Path(shared_chunks).mkdir(parents=True, exist_ok=True)
        self.store.create(shared_chunks)
        self.actions = {a['id']: a for a in actions}
        self.replay = self.out.parent
        self.discovery = commands(actions)
        self.by_action = defaultdict(list)
        for row in self.discovery['invocations']:
            self.by_action[row['action_id']].append(row)
        self.blobs, self.versions, self.snapshots, self.executions = set(), set(), {}, []
        self.source_literals = []
        for candidate in self.discovery['source_literals']:
            raw = candidate['content'].encode()
            digest = hashlib.sha256(raw).hexdigest()
            if digest not in self.blobs:
                self.store.put(raw)
                self.blobs.add(digest)
            self.source_literals.append({'action_id': candidate['action_id'], 'path': candidate['path'],
                                         'sha256': digest})
        self.parsed = {}
        self.latest, self.terminal = None, None

    def _capture(self, runtime, label):
        request = {'known_blobs': sorted(self.blobs), 'extra_paths': self.discovery['extra_paths'],
                   'all_sources':self.trace_commands and label in {'initial','submission'}}
        process = runtime.control(['python3', '-I', '-c', SNAPSHOT_SCRIPT],
                                  input_bytes=json.dumps(request).encode(), timeout=180)
        observation = json.loads(process.stdout)
        for digest, encoded in observation.pop('blobs').items():
            if digest not in self.blobs:
                self.store.put(base64.b64decode(encoded))
                self.blobs.add(digest)
        for row in observation['files']:
            if row['kind'] == 'file':
                self.versions.add((row['path'], row['sha256']))
        if self.latest and observation['files'] == self.latest['files'] and label != 'submission':
            return self.latest
        observation['label'] = label
        write_json(self.out / 'snapshots' / (label + '.json'), observation)
        self.snapshots[label] = observation
        self.latest = observation
        return observation

    def start(self, runtime):
        self._capture(runtime, 'initial')

    def before_action(self, runtime, action):
        if self.by_action[action['id']]:
            self.before = self._capture(runtime, action['id'] + '_before')

    def run_action(self,runtime,action):
        return runtime.run(action['command'],action['id'])

    def after_action(self, runtime, action, result):
        after = self._capture(runtime, action['id'] + '_after')
        directory = runtime.output / 'calls' / action['id']
        if not self.by_action[action['id']]:
            return
        raw_output = (directory / 'output.bin').read_bytes()
        event = {'action_id': action['id'], 'replay_output': str(directory / 'output.bin'),
                 'before_snapshot': self.before['label'], 'after_snapshot': after['label']}
        self.executions.append((event, raw_output.decode(errors='replace')))
        saved={**event,'replay_output':os.path.relpath(directory/'output.bin',self.out/'executions')}
        write_json(self.out / 'executions' / (action['id'] + '.json'), saved)

    def capture_submission(self, frozen):
        # Observe the committed filesystem checkpoint, not a running replay's
        # mutable terminal state or the post-test baseline workspace.
        self.terminal = self._capture(frozen, 'submission')

    def _parse(self, path, digest):
        key = (path, digest)
        if key not in self.parsed:
            self.parsed[key] = discover(path, self.store.read(digest))
        return self.parsed[key]

    def _definitions(self, files):
        return [unit for row in files if row['kind'] == 'file'
                for unit in self._parse(row['path'], row['sha256'])['units']]

    def finish(self, checkpoint, validation):
        links = defaultdict(list)
        for event, output in self.executions:
            before = self.snapshots[event['before_snapshot']]
            after = self.snapshots[event['after_snapshot']]
            pre = {r['path']: r.get('sha256') for r in before['files']}
            post = {r['path']: r.get('sha256') for r in after['files']}
            versions = {(u['path'], u['name'], u['source_sha256'], u['id']): u
                        for u in self._definitions(before['files']) + self._definitions(after['files'])}
            invocations = self.by_action[event['action_id']]
            runner_counts = Counter(i['framework'] for i in invocations)
            original_output = self.actions[event['action_id']]['expected'].get('output', '')
            for invocation in invocations:
                selected = [u for u in versions.values() if in_scope(u, invocation)]
                notices = result_notices(output, invocation['framework'])
                reports = {'original': named_results(original_output, invocation['framework']),
                           'replay': named_results(output, invocation['framework'])}
                for unit in selected:
                    key = (unit['path'], unit['name'], unit['source_sha256'], unit['id'])
                    matched, ambiguous = {}, {}
                    for origin, rows in reports.items():
                        matching = [r for r in rows if result_matches(unit, r, invocation['working_directory'])]
                        matched[origin] = [r for r in matching if len({
                            (u['path'], u['name'], u['id']) for u in selected
                            if result_matches(u, r, invocation['working_directory'])}) == 1]
                        ambiguous[origin] = [r for r in matching if r not in matched[origin]]
                    # Suite membership is not a per-test execution observation.
                    if not any(matched.values()) and not any(ambiguous.values()):
                        continue
                    stable = (pre.get(unit['path']) == post.get(unit['path']) == unit['source_sha256']
                              and not source_may_change_during_action(invocation, unit, self.discovery))
                    unambiguous = runner_counts[invocation['framework']] == 1
                    # Named skipped/xfailed results do not prove test body execution.
                    reported = any(r['status'] in {'passed', 'failed', 'xpass'} for r in matched['replay'])
                    association = {'invocation_id': invocation['id'],
                        'source_binding': 'equal_bracketing_snapshots' if stable else 'version_within_command_unresolved',
                        'report_binding': 'one_runner_in_action' if unambiguous else 'multiple_runners_unresolved',
                        'original_named_reports': matched['original'], 'replay_named_reports': matched['replay'],
                        'test_execution': 'named_report_observed' if stable and unambiguous and reported and not notices else 'unconfirmed',
                        'execution_notices': notices}
                    if any(ambiguous.values()):
                        association['ambiguous_named_reports'] = ambiguous
                    links[key].append(association)
        terminal = {r['path']: r for r in self.terminal['files'] if r.get('kind') == 'file'}
        tests = []
        for path, digest in sorted(self.versions):
            for unit in self._parse(path, digest)['units']:
                associations = links[(unit['path'], unit['name'], unit['source_sha256'], unit['id'])]
                row = {**unit,
                       'retained_at_submission': unit['path'].startswith('/app/') and terminal.get(unit['path'], {}).get('sha256') == unit['source_sha256'],
                       'historical_associations': associations,
                       'execution_status': 'named_report_observed' if any(x['test_execution'] == 'named_report_observed' for x in associations) else 'unconfirmed'}
                tests.append(row)
        parsed_errors = [{'path': p, 'sha256': s, 'reason': v['reason']} for (p, s), v in self.parsed.items() if v['status'] == 'unresolved']
        manifest = {'replay': os.path.relpath(self.replay,self.out), 'checkpoint': checkpoint,
                    'submission_state_validated': validation['matched'], 'tests': tests,
                    'source_versions': [{'path': p, 'sha256': s} for p, s in sorted(self.versions)],
                    'unobserved_source_candidates': [s for s in self.source_literals if (s['path'], s['sha256']) not in self.versions],
                    'invocations': [{k: i[k] for k in ('id', 'action_id', 'framework', 'working_directory', 'command_offsets')}
                                    for i in self.discovery['invocations']],
                    'unresolved_commands': self.discovery['issues'],
                    'parse_errors': parsed_errors}
        write_json(self.out / 'manifest.json', manifest)
        return {'manifest': str(self.out / 'manifest.json')}


def read_source(manifest_path, source_path, *, sha256=None):
    """Retrieve final or explicitly selected historical bytes from replay CAS."""
    manifest = read_json(manifest_path)
    if sha256 is None:
        snapshot = read_json(Path(manifest_path).resolve().parent / 'snapshots/submission.json')
        sha256 = {v['path']: v['sha256'] for v in snapshot['files'] if v['kind'] == 'file'}[source_path]
    return BlobStore(Path(manifest_path).resolve().parent / 'blobs').read(sha256)


class ReplayTrajectoryCollector(ReplayTestCollector):
    """Add process/file IO to A, keeping B records and replay independent."""
    trace_commands=True

    def start(self,runtime):
        from .trajectory import Trajectory
        super().start(runtime)
        self.trajectory=Trajectory(self.out)
        self.trajectory.start(self.snapshots['initial'])

    def run_action(self,runtime,action):
        script=BLOB_SCRIPT+'\n'+Path(__file__).with_name('trace_guest.py').read_text()
        script+='\nprint(json.dumps(execute(json.load(sys.stdin),BlobStore)))\n'
        return runtime.run(action['command'],action['id'],observer_script=script)

    def after_action(self,runtime,action,result):
        from .trajectory import read_trace
        rows=read_trace(result);executions={r['id']:r for r in rows if r['kind']=='exec'}
        batches=defaultdict(list);sources={};versions={}
        for row in rows:
            binding=row.get('bytecode_source')
            if (binding is not None and 'version' in binding and not binding['equivalent'] and
                    executions[row['execution']]['python'] is not None):
                path=binding['version']['path'];candidates={digest for p,digest in self.versions if p==path}
                candidates.add(binding['version']['sha256'])
                for digest in candidates:
                    if digest not in sources:
                        store=self.store if digest in self.blobs else BlobStore(Path(result['trace'])/'blobs')
                        sources[digest]=base64.b64encode(store.read(digest)).decode()
                    versions[path,digest]={'path':path,'sha256':digest}
                match=re.search(r'\.opt-([12])\.',row['version']['path'])
                batches[executions[row['execution']]['python']].append({'event':str(row['id']),
                    'cache':row['version']['sha256'],'sources':sorted(candidates),'rewrite':'-pytest-' in row['version']['path'],
                    'optimize':int(match[1]) if match else 0})
        proofs={}
        for python,entries in batches.items():
            request={'blobs':result['trace_guest_directory']+'/blobs','entries':entries,'sources':sources}
            script=BLOB_SCRIPT+'\n'+Path(__file__).with_name('python_cache_guest.py').read_text()
            script+='\nprint(json.dumps(verify(json.load(sys.stdin),BlobStore)))\n'
            process=runtime.control([python,'-B','-I','-c',script],input_bytes=json.dumps(request).encode())
            proofs.update(json.loads(process.stdout))
        write_json(Path(result['trace'])/'cache_bindings.json',proofs)
        for row in rows:
            if str(row['id']) in proofs:
                proof=proofs[str(row['id'])];binding=row['bytecode_source']
                binding['basis']=proof['basis']
                binding['equivalent_versions']=[versions[binding['version']['path'],sha] for sha in proof['matched_sources']]
        self.trajectory.add_action(action,result,rows)
        # The trace keeps a usable store reference, while the case owns one
        # copy of each version and the run may share chunks between cases.
        trace_blobs=Path(result['trace'])/'blobs'
        shutil.rmtree(trace_blobs)
        trace_blobs.symlink_to(os.path.relpath(self.store.directory,trace_blobs.parent),target_is_directory=True)
        for material in self.trajectory.materials.values():
            if material['kind']=='file':
                self.versions.add((material['path'],material['sha256']))
                self.blobs.add(material['sha256'])
        super().after_action(runtime,action,result)
        runtime.control(['rm','-rf',result['trace_guest_directory']])

    def finish(self,checkpoint,validation):
        self.trajectory.finish(self.terminal)
        result=super().finish(checkpoint,validation)
        manifest=read_json(result['manifest']);manifest['trajectory']='trajectory.json'
        write_json(result['manifest'],manifest)
        return {**result,'trajectory':str(self.out/'trajectory.json')}
