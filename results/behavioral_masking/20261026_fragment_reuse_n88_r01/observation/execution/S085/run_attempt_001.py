from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT / 'src'))
from context_recovery_pilot1_runtime import execute_plan

ATTEMPT = Path(__file__).parent / 'attempt_001'
manifest = json.loads((ATTEMPT / 'manifest.json').read_text())


def execute(row):
    plan_path = Path(row['plan']['path'])
    raw = plan_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == row['plan']['sha256']
    print(json.dumps({'event': 'start', 'id': row['id']}), flush=True)
    result = execute_plan(json.loads(raw), Path(row['out']), base_directory=plan_path.parent)
    summary = {'id': row['id'], 'status': result.get('status'),
               'target_executed': result.get('target_executed'),
               'execution_returncode': result.get('execution', {}).get('returncode'),
               'failed_step': result.get('failed_step')}
    print(json.dumps(summary), flush=True)
    return summary


with ThreadPoolExecutor(max_workers=2) as pool:
    futures = {pool.submit(execute, row): row for row in manifest['plans']}
    completed = [future.result() for future in as_completed(futures)]
with (ATTEMPT / 'runner_completion.json').open('x') as stream:
    json.dump({'completed': completed, 'semantic_outcomes': 'not_inferred_from_exit_status'}, stream, indent=2)
    stream.write('\n')
