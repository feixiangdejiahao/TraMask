"""Legacy experiment entry point; replay is implemented in eviweave.replay."""
from pathlib import Path

from eviweave.artifacts import read_json
from eviweave.replay import INPUT_NAMES, resolve_task_base_commit
from eviweave.replay import core
from eviweave.replay.container import Container


def replay_case(case, input_dir, out, *, collect_validation_tests=False):
    if collect_validation_tests:
        from eviweave.collection import collect_tests
        return collect_tests(case, input_dir, out)
    return core.replay_case(case, input_dir, out)


def inspect_image_availability(image):
    process = Container.docker(['image', 'inspect', '--format', '{{.Id}}', image], check=False)
    return {'image': image, 'available': process.returncode == 0,
            'image_id': process.stdout.decode().strip() if process.returncode == 0 else None,
            'stderr': process.stderr.decode(errors='replace')}


def inspect_attempt(out):
    out = Path(out)
    if not out.exists():
        return {'status': 'not_started', 'directory': str(out)}
    complete = (out / 'completion.json').exists()
    return {'status': 'complete' if complete else 'requires_new_attempt', 'directory': str(out),
            'can_reuse_recorded_result': complete, 'can_resume_commands': False,
            'checkpoint': read_json(out / 'checkpoint.json') if (out / 'checkpoint.json').exists() else None}
