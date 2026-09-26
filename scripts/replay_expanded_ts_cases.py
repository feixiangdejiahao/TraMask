"""Two small retrospective witnesses through the already copied replay driver.

Only the public submitted candidate patch and explicit witness are mounted.
No verifier or reference implementation is available inside these containers.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'results/expanded_trials_20260926'
CASES = {
    'koota_deferred': ('koota-deferred-mutation-buffer__whVuJZW',
                      'research_combination.test.ts',
                      '/app/packages/core/tests/research_combination.test.ts',
                      'pnpm --filter @koota/core exec vitest run tests/deferred.test.ts tests/research_combination.test.ts --reporter=verbose'),
    'dynamodb': ('dynamodb-toolbox-conditional-att__dRJudvE',
                 'research_combination.unit.test.ts',
                 '/app/src/schema/actions/research_combination.unit.test.ts',
                 'npx --no-install vitest run src/schema/actions/requiredIf.unit.test.ts src/schema/actions/zodSchemer/parser/item.unit.test.ts src/schema/actions/research_combination.unit.test.ts --reporter=verbose'),
}


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('case', choices=CASES)
    args = parser.parse_args()
    trial, witness, target, command = CASES[args.case]
    base = OUT / 'trials' / trial
    out = OUT / 'replays' / args.case
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'scripts/expanded_trials_20260926/probes' / args.case / witness,
                 out / witness)
    config = tomllib.loads((base / 'task.toml').read_text())
    image = config['environment']['docker_image']
    image_id = subprocess.check_output(['docker', 'image', 'inspect', image, '--format', '{{.Id}}'], text=True).strip()
    request = dict(program='candidate', command='git rev-parse HEAD\n' + command,
                   language='typescript', coverage=False, timeout=180,
                   uid=os.getuid(), gid=os.getgid())
    cmd = ['docker', 'run', '--rm', '--interactive', '--init', '--network', 'none',
           '--cpus', '2', '--memory', '8g', '--pull', 'never',
           '--mount', f'type=bind,src={ROOT / "vendor/replay/container_replay.py"},dst=/replay.py,readonly',
           '--mount', f'type=bind,src={out},dst=/replay-logs',
           '--mount', f'type=bind,src={base / "model.patch"},dst=/candidate.patch,readonly',
           '--mount', f'type=bind,src={out / witness},dst={target},readonly',
           '--entrypoint', 'python3', image, '/replay.py']
    manifest = {'role': 'retrospective failure reproduction', 'trial': trial,
                'request': request, 'docker_command': cmd, 'image_id': image_id,
                'expected_base_commit': config['metadata']['base_commit_hash'],
                'sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in [base / 'model.patch', out / witness, ROOT / 'vendor/replay/container_replay.py']}}
    (out / 'replay_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    result = subprocess.run(cmd, input=json.dumps(request), text=True,
                            capture_output=True, timeout=240)
    (out / 'transport.stdout').write_text(result.stdout)
    (out / 'transport.stderr').write_text(result.stderr)
    print(json.dumps({'case': args.case, 'transport_returncode': result.returncode,
                      'result': json.loads((out / 'result.json').read_text())
                      if (out / 'result.json').exists() else None}))


if __name__ == '__main__':
    main()
