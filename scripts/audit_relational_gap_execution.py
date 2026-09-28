"""Summarize persisted provider and phase artifacts without running subjects."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def read(path):
    return json.loads(path.read_text())


def audit(prefix):
    groups, providers, missing = [], [], []
    for manifest_path in sorted(Path(str(prefix) + '_emitted').glob('*/group_*/manifest.json')):
        manifest = read(manifest_path)
        destination = Path(str(prefix) + '_runs') / manifest_path.parent.parent.name / manifest_path.parent.name
        phases = {}
        for role in ('control', 'generated'):
            folder = destination / role
            if not (folder / 'normalized.json').exists():
                missing.append(str(folder))
                continue
            normalized = read(folder / 'normalized.json')
            phase = read(folder / 'result.json') if (folder / 'result.json').exists() else {}
            diagnostics = []
            go = folder / 'go.jsonl'
            if go.exists():
                for line in go.read_text(errors='replace').splitlines():
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get('Action') == 'build-output':
                        diagnostics.extend(row.get('Output', '').splitlines())
            phases[role] = {'errors': normalized['errors'], 'status': normalized['status'],
                            'counts': normalized['counts'], 'timed_out': phase.get('timed_out', False),
                            'elapsed_seconds': phase.get('elapsed_seconds'), 'build_diagnostics': diagnostics,
                            'tests': normalized['tests']}
        if len(phases) != 2:
            continue
        generated, control = phases['generated'], phases['control']
        compile_errors = [line for line in generated['build_diagnostics']
                          if re.match(r'.*\.go:\d+:\d+:', line)]
        category = None
        if compile_errors:
            if not control['build_diagnostics'] and not control['errors']:
                category = 'generated_compile_failure_controls_executable'
            elif all('undefined:' in line or 'too many errors' in line for line in compile_errors):
                category = 'source_dependency_or_import_missing'
            else:
                category = 'compile_failure_also_affects_controls'
        observed_ids = {row['id'] for row in generated['tests'] if row['status'] in ('pass', 'fail')}
        unobserved = [row['candidate_id'] for row in manifest['obligations']
                      if not any(name == row['id'] or name.endswith('::' + row['id']) or name.strip() == row['id']
                                 for name in observed_ids)]
        for phase in phases.values():
            phase.pop('tests')
        groups.append({'case': manifest['case'], 'group': manifest_path.parent.name,
                       'lane': manifest['execution_lane'], 'candidate_count': len(manifest['obligations']),
                       'candidate_ids': [row['candidate_id'] for row in manifest['obligations']],
                       'unobserved_candidates': unobserved, 'compile_category': category,
                       'manifest': str(manifest_path.resolve()), 'phases': phases})
    for path in sorted(Path(str(prefix) + '_completions').glob('*/*/manifest.json')):
        row = read(path)
        validation_path = path.parent / 'validation.json'
        validation = read(validation_path) if validation_path.exists() else {}
        providers.append({'case': path.parent.parent.name, 'request': path.parent.name,
                          'status': row['status'], 'model': row['model'], 'usage': row.get('usage', {}),
                          'seconds': row.get('seconds'), 'protocol_error': validation.get('protocol_error'),
                          'accepted_count': len(validation.get('accepted', [])),
                          'manifest_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    categories = sorted({row['compile_category'] for row in groups if row['compile_category']})
    return {'groups': groups, 'providers': providers, 'missing_phase_reports': missing,
            'summary': {'groups': len(groups), 'provider_calls': len(providers),
                        'provider_status': dict(Counter(row['status'] for row in providers)),
                        'protocol_valid': sum(not row['protocol_error'] for row in providers),
                        'prompt_tokens': sum(row['usage'].get('prompt_tokens', 0) for row in providers),
                        'completion_tokens': sum(row['usage'].get('completion_tokens', 0) for row in providers),
                        'total_tokens': sum(row['usage'].get('total_tokens', 0) for row in providers),
                        'generated_error_groups': sum(bool(row['phases']['generated']['errors']) for row in groups),
                        'control_error_groups': sum(bool(row['phases']['control']['errors']) for row in groups),
                        'timeout_groups': sum(any(p['timed_out'] for p in row['phases'].values()) for row in groups),
                        'source_q_compile_categories': {category: {
                            'groups': sum(row['lane'] == 'source_q' and row['compile_category'] == category for row in groups),
                            'candidates': sum(row['candidate_count'] for row in groups
                                              if row['lane'] == 'source_q' and row['compile_category'] == category)}
                            for category in categories}}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--prefix', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.prefix)
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result['summary']))


if __name__ == '__main__':
    main()
