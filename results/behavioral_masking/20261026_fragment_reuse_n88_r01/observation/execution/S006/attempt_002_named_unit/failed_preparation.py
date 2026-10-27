"""Retain the prespecified named unit after unrelated file-level R type errors."""
from pathlib import Path
import hashlib
import json
import re

HERE = Path(__file__).parent
OLD, OUT = HERE / 'attempt_001', HERE / 'attempt_002_named_unit'
OUT.mkdir(exist_ok=False)
manifest = json.loads((OLD / 'manifest.json').read_text())
name = manifest['selected_test']
pattern = re.compile(r"  it\('" + re.escape(name) + r"', async \(\) => \{.*?\n  \}\)", re.S)
plans = []


def receipt(path):
    return {'path': str(path), 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


for variant in manifest['candidate_order']:
    original_path = OLD / 'prepared' / variant / 'container.initialize.test.ts'
    original = original_path.read_text()
    body = pattern.search(original).group()
    imports = ["import { createContainer } from '../container'", "import { asFunction } from '../resolvers'"]
    assert imports[0] in original and "import { asClass, asFunction } from '../resolvers'" in original
    # Preserve the complete selected it() body byte-for-byte. Only unrelated
    # named tests and their unused declarations/imports are not copied.
    isolated = '\n'.join(imports) + "\n\ndescribe('container.initialize', () => {\n" + body + '\n})\n'
    prepared = OUT / 'prepared' / variant
    prepared.mkdir(parents=True)
    path = prepared / 'fragment_S006.test.ts'
    path.write_text(isolated)
    write(prepared / 'frozen.json', {'file': receipt(path), 'prior_source': receipt(original_path),
          'selected_named_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
          'selected_body_unchanged_from_same_variant': True,
          'removed_scope': '19 unrelated named tests, unused classes/imports; no selected-unit expression changed'})
    for prior in [p for p in manifest['plans'] if p['variant'] == variant]:
        plan = json.loads(Path(prior['plan']['path']).read_text())
        plan['files'] = [{'source': str(path), 'destination': '/app/src/__tests__/fragment_S006.test.ts'}]
        plan['command'] = './node_modules/.bin/jest --runInBand src/__tests__/fragment_S006.test.ts -t "limits concurrency within a level"'
        plan_path = OUT / 'plans' / (prior['id'] + '.json')
        write(plan_path, plan)
        plans.append({**{k:prior[k] for k in ('id','variant','implementation','repeat')},
                      'plan': receipt(plan_path), 'out': str(OUT / 'runs' / prior['id'])})
write(OUT / 'manifest.json', {**{k:v for k,v in manifest.items() if k != 'plans'},
      'scope': 'prespecified complete named unit extracted verbatim into its own file',
      'scope_change_timing': 'after attempt001 reference compile failures in11 unrelated test locations; retain all attempt001 results',
      'prior_manifest': receipt(OLD / 'manifest.json'), 'preparation_script': receipt(Path(__file__)),
      'selected_body_changes_after_reference_feedback': False,
      'whole_original_test_file_repaired': False, 'plans': plans})
runner = (HERE / 'run_attempt_001.py').read_text().replace("'attempt_001'", "'attempt_002_named_unit'")
(HERE / 'run_attempt_002.py').write_text(runner)
print(json.dumps({'out': str(OUT), 'plans': len(plans)}))
