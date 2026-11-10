"""Download a fixed, paired small sample of public DeepSWE failure artifacts."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
SNAPSHOT = Path('/home/jhx/oracle_gap/data/raw/deepswe/snapshots/trials.json')
COHORT = Path('/home/jhx/combination_coverage/results/behavioral_masking/20261026_fragment_reuse_n88_r01/cases.json')
MODELS = ['glm-5-3-flash', 'qwen3-8-max']
rows = json.loads(SNAPSHOT.read_text())['rows']
cases = json.loads(COHORT.read_text())['cases']
ordered_tasks = list(dict.fromkeys(c['task'] for c in cases))
model_rows = [r for r in rows if r['model'] in MODELS]
(ROOT / 'sources' / 'target_model_metadata.json').write_text(json.dumps(model_rows, indent=2) + '\n')
eligible = {model: {} for model in MODELS}
for model in MODELS:
    for row in model_rows:
        if (row['model'] == model and row['task_name'] in ordered_tasks
            and row['outcome'] == 'fail' and not row['errored']
            and row['has_trajectory'] and row['has_model_patch'] and row['has_verifier_output']):
            eligible[model].setdefault(row['task_name'], []).append(row)
common = [task for task in ordered_tasks if all(task in eligible[model] for model in MODELS)]
selected_tasks = common[:5]
selected = [min(eligible[model][task], key=lambda row: row['trial_name'])
            for task in selected_tasks for model in MODELS]
selection = {
    'policy': 'Take first five distinct tasks in original 88-case order for which both target models have a non-error failed run with advertised trajectory, model patch and verifier output; choose lexicographically first trial_name per model and task before examining trajectory contents.',
    'source_snapshot': str(SNAPSHOT),
    'source_sha256': hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest(),
    'source_cohort': str(COHORT),
    'cohort_sha256': hashlib.sha256(COHORT.read_bytes()).hexdigest(),
    'models': MODELS,
    'eligible_counts': {m: sum(map(len, eligible[m].values())) for m in MODELS},
    'eligible_task_counts': {m: len(eligible[m]) for m in MODELS},
    'common_eligible_task_count': len(common),
    'common_eligible_tasks_in_order': common,
    'selected_tasks': selected_tasks,
    'task_selection_audit': [{'task': task, 'eligible_failure_runs': {m:len(eligible[m].get(task, [])) for m in MODELS},
                              'selected':task in selected_tasks,
                              'reason':'selected_by_fixed_order' if task in selected_tasks else ('outside_first_five' if task in common else 'no_eligible_failed_run_in_one_or_both_models')}
                             for task in ordered_tasks],
    'selected': selected,
}
(ROOT / 'selection.json').write_text(json.dumps(selection, indent=2) + '\n')
release = json.loads((ROOT / 'sources' / 'deepswe_current_release.json').read_text())
base = release['artifact_base_url'] + '/' + release['artifact_key_prefix']
artifacts = [('agent/trajectory.json', 'trajectory.json'), ('artifacts/model.patch', 'model.patch'),
             ('verifier/ctrf.json', 'ctrf.json'), ('verifier/reward.json', 'reward.json'),
             ('verifier/test-stdout.txt', 'test-stdout.txt')]

def download(item):
    row, remote, local = item
    directory = ROOT / 'trials' / row['trial_name']
    directory.mkdir(parents=True, exist_ok=True)
    url = base + '/' + row['trial_name'] + '/' + remote
    req = urllib.request.Request(url, headers={'User-Agent':'EviWeave-research-public-data-audit'})
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            body = response.read()
            status = response.status
    except urllib.error.HTTPError as error:
        return {'url':url, 'trial_name':row['trial_name'], 'artifact':local,
                'http_status':error.code, 'error':str(error)}
    path = directory / local
    path.write_bytes(body)
    return {'url':url, 'trial_name':row['trial_name'], 'artifact':local, 'local':str(path),
            'http_status':status, 'bytes':len(body), 'sha256':hashlib.sha256(body).hexdigest()}

items = [(row, remote, local) for row in selected for remote, local in artifacts]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    manifests = list(pool.map(download, items))
(ROOT / 'download_manifest.json').write_text(json.dumps(manifests, indent=2) + '\n')
for row in selected:
    (ROOT / 'trials' / row['trial_name'] / 'metadata.json').write_text(json.dumps(row, indent=2) + '\n')
print(json.dumps({'tasks':selected_tasks, 'trials':[r['trial_name'] for r in selected],
                  'downloads':len(manifests),'bytes':sum(r.get('bytes',0) for r in manifests),
                  'errors':[r for r in manifests if 'error' in r]}, indent=2))
