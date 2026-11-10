#!/usr/bin/env python3
"""Prepare lossless readable trajectories and evaluation failures for manual review."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import textwrap


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'results/behavioral_masking/20261026_fragment_reuse_n88_r01'


def readable(value):
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def observation(value):
    """Decode the tool's JSON string envelope without dropping any fields."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    if isinstance(parsed, dict):
        return '\n'.join(str(k) + ':\n' + readable(v) for k, v in parsed.items())
    return readable(parsed)


def prepare(case, out):
    sid = case['screen_id']
    directory = out / 'cases' / sid
    directory.mkdir(parents=True)
    original = Path(case['input_directory']) / 'trajectory.json'
    raw = original.read_bytes()
    trajectory = json.loads(raw)
    (directory / 'trajectory_metadata.json').write_text(json.dumps(
        {key: value for key, value in trajectory.items() if key != 'steps'},
        ensure_ascii=False, indent=2) + '\n')
    parts = []
    steps = []
    line = 1
    calls = 0
    for step in trajectory['steps']:
        lines = [f"STEP {step['step_id']} SOURCE {step['source']}"]
        for field in ('reasoning_content', 'message'):
            if field in step:
                lines.append(field.upper())
                for paragraph in readable(step[field]).splitlines():
                    lines.extend(textwrap.wrap(paragraph, 150, break_long_words=False,
                                               break_on_hyphens=False) or [''])
        for i, call in enumerate(step.get('tool_calls', [])):
            calls += 1
            lines.extend([f"CALL s{step['step_id']}_c{i} TOOL_ID {call['tool_call_id']}",
                          'FUNCTION ' + call['function_name'], 'ARGUMENTS'])
            for key, value in call['arguments'].items():
                lines.extend([key + ':', readable(value)])
        if 'observation' in step:
            for i, result in enumerate(step['observation']['results']):
                lines.append('OBSERVATION ' + str(i))
                for key, value in result.items():
                    lines.extend([key + ':', observation(value) if key == 'content' else readable(value)])
        rest = {key: value for key, value in step.items()
                if key not in {'step_id', 'source', 'reasoning_content', 'message', 'tool_calls', 'observation'}}
        if rest:
            lines.extend(['OTHER STEP FIELDS', readable(rest)])
        text = '\n'.join(lines) + '\n\n'
        count = text.count('\n')
        steps.append({'step': step['step_id'], 'first_line': line, 'last_line': line + count - 1})
        line += count
        parts.append(text)
    (directory / 'fulltext.txt').write_text(''.join(parts))
    ctrf = Path(case['archived_verifier_directory']) / 'ctrf.json'
    tests = json.loads(ctrf.read_bytes())['results']['tests']
    failures = [test for test in tests if test['status'] == 'failed']
    (directory / 'evaluation_failures.json').write_text(json.dumps({
        'source': str(ctrf), 'status_counts': dict(Counter(t['status'] for t in tests)),
        'failed_tests': failures}, ensure_ascii=False, indent=2) + '\n')
    metadata = {**case, 'trajectory': str(original), 'trajectory_sha256': hashlib.sha256(raw).hexdigest(),
                'steps': len(trajectory['steps']), 'calls': calls, 'fulltext_lines': line - 1,
                'step_lines': steps,
                'issue': str(Path(case['input_directory']) / 'instruction.md'),
                'patch': str(Path(case['input_directory']) / 'model.patch'),
                'verifier_patch': str(Path(case['task_directory']) / 'tests/test.patch'),
                'prior_adjudication': str(SOURCE / 'observation/adjudicated' / (sid + '.json')),
                'repository_materials': str(SOURCE / 'public_workspace_v3/cases' / sid / 'inventory.json')}
    (directory / 'case.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + '\n')
    return {'case': sid, 'task': case['task'], 'language': case['language'],
            'steps': len(trajectory['steps']), 'lines': line - 1, 'failed_tests': len(failures)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True)
    cases = json.loads((SOURCE / 'cases.json').read_bytes())['cases']
    rows = [prepare(case, out) for case in cases]
    (out / 'case_index.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'cases': len(rows), 'steps': sum(r['steps'] for r in rows),
                      'failed_tests': sum(r['failed_tests'] for r in rows),
                      'readable_lines': sum(r['lines'] for r in rows)}))


if __name__ == '__main__':
    main()
