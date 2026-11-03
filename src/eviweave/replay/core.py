"""Chronological replay. Optional observers read state; replay owns execution."""
from pathlib import Path
import shutil
import tomllib

from ..artifacts import file_ref, read_json, write_json
from .container import Container, ENV, open_container
from .state import original_gitlinks, validate_submission_state
from .trajectory import resolve_submission_actions


INPUT_NAMES = ('instruction.md', 'task.toml', 'model.patch', 'trajectory.json')


def resolve_task_base_commit(configured, case):
    full = case['base_commit']
    if configured == full:
        return {'configured': configured, 'resolved': full, 'resolution': 'already_full'}
    if not full.startswith(configured):
        raise ValueError('case_identity_differs_from_explicit_task_configuration')
    result = Container.docker(['run', '--rm', '--network', 'none', '--entrypoint', 'git',
                               case['image'], '-C', '/app', 'rev-parse', configured + '^{commit}'], check=False)
    if result.returncode or result.stdout.decode().strip() != full:
        raise ValueError('task_abbreviated_base_does_not_resolve_to_case_commit')
    return {'configured': configured, 'resolved': full, 'resolution': 'git_in_original_image'}


def load_case(case_id, input_directory, base_commit=None):
    config = tomllib.loads((Path(input_directory) / 'task.toml').read_text())
    case = {'id': case_id, 'image': config['environment']['docker_image'],
            'base_commit': base_commit or config['metadata']['base_commit_hash']}
    # Resolve short revisions once at the input boundary, before replay starts.
    if len(case['base_commit']) < 40:
        result = Container.docker(['run', '--rm', '--network', 'none', '--entrypoint', 'git',
                                   case['image'], '-C', '/app', 'rev-parse', case['base_commit'] + '^{commit}'])
        case['base_commit'] = result.stdout.decode().strip()
    elif base_commit:
        resolve_task_base_commit(config['metadata']['base_commit_hash'], case)
    return case


def replay_case(case, input_directory, out, *, observer_factory=None):
    """Freeze four raw inputs, execute every observed action, validate checkpoint.

    A new run needs a new output directory. Command failures/timeouts are data;
    Docker, parser and observer failures propagate to the caller.
    """
    source, out = Path(input_directory), Path(out).resolve()
    config = tomllib.loads((source / 'task.toml').read_text())
    actions, boundary = resolve_submission_actions(read_json(source / 'trajectory.json'))
    out.mkdir(parents=True)
    inputs = out / 'inputs'
    inputs.mkdir()
    for name in INPUT_NAMES:
        shutil.copyfile(source / name, inputs / name)
    input_refs = {name: {**file_ref(inputs / name),'path':'inputs/'+name} for name in INPUT_NAMES}
    observer = observer_factory(actions, input_refs, case) if observer_factory else None
    resources = {'cpus': config['environment'].get('cpus', 2),
                 'memory': str(config['environment'].get('memory_mb', 8192)) + 'm'}
    write_json(out / 'plan.json', {'case': case, 'inputs': input_refs,
                                  'boundary': boundary, 'action_ids': [a['id'] for a in actions],
                                  'environment_overlay': ENV, 'timeout': 30, 'resources': resources})
    records = []
    with open_container(case['image'], case['base_commit'], out / 'runtime',
                        trace_commands=observer.trace_commands if observer else False,**resources) as runtime:
        gitlinks = original_gitlinks(runtime)
        if observer:
            observer.start(runtime)
        for action in actions:
            write_json(out / 'progress.json', {'completed_actions': len(records), 'action_id': action['id']})
            if observer:
                observer.before_action(runtime, action)
            result = observer.run_action(runtime,action) if observer else runtime.run(action['command'], action['id'])
            write_json(runtime.output / 'calls' / action['id'] / 'archived_expected.json', action['expected'])
            result['original_returncode'] = action['expected']['returncode']
            records.append(result)
            if observer:
                observer.after_action(runtime, action, result)
        checkpoint = runtime.checkpoint()
        write_json(out / 'checkpoint.json', checkpoint)
    with open_container(checkpoint['image_id'], checkpoint['head'], out / 'frozen_state', **resources) as frozen:
        if observer:
            observer.capture_submission(frozen)
        validation = validate_submission_state(frozen, inputs / 'model.patch', out / 'validation',
                                               base_commit=case['base_commit'], gitlink_baseline=gitlinks)
    collection = observer.finish(checkpoint, validation) if observer else None
    result = {'id': case['id'], 'status': 'replayed', 'actions_executed': len(records),
              'action_ids': [r['id'] for r in records], 'checkpoint': checkpoint,
              'observed_submission_boundary': boundary, 'validation': validation,
              'state_validation_passed': validation['matched'], 'step_a': collection,
              'timeouts': [r['id'] for r in records if r['timed_out']],
              'returncode_differences': [r['id'] for r in records if r['returncode'] != r['original_returncode']]}
    saved={**result,'step_a':{k:str(Path(v).relative_to(out)) for k,v in collection.items()} if collection else None}
    write_json(out / 'summary.json', saved)
    reference = {**checkpoint, 'summary': str(out / 'summary.json'),
                 'state_validation_passed': validation['matched']}
    write_json(out / 'checkpoint_reference.json', {**reference,'summary':'summary.json'})
    write_json(out / 'progress.json', {'completed_actions': len(records), 'status': 'completed'})
    write_json(out / 'completion.json', {'summary': 'summary.json'})
    return {**result, 'study_checkpoint': reference}
