"""Replay complete archived summaries with fixed round01 -> declaration order.

No subject execution, provider dispatch, or evaluation-label input exists here.
Provenance roles are versioned: execution components expand; source-cohort data
does not expand into an execution dependency merely because it is named prepared.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'archived-complete-component-chain.v1'
CHAIN = 'ordered-source-relation-exact-semantic-chain.v4'
CODEC = 'codec-guarded-exact-semantic-replay.v2'
GATE = 'exact-payload-second-gate-replay.v1'
NATIVE = {
    'documented-default-search.v1',
    'controlled-guest-carrier-inverse-search.v1',
    'controlled-http-error-finalization-search.v1',
    'controlled-guest-declaration-order-search.v1',
}
ARCHIVES = {
    'round01': '759df9cdcb8118418e80c24654e1de00d75ce3ab',
    'declaration': '2594216b3ffbf607ffa9b98794074b62531ac156',
}
COHORT_USES = {
    'Only the trial list and source snapshot paths; no candidates or outcomes read.',
    'Only trial list and original source snapshot paths. No old candidates or outcomes.',
    'Only original snapshot paths and the full trial list; no old candidates or outcomes.',
}
INPUTS = {'corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md'}


def read(path):
    return json.loads(Path(path).read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def frozen(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if read(path) != value:
            raise ValueError('Immutable artifact differs: ' + str(path))
        return
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Verifier:
    def __init__(self, root, commit):
        self.root = Path(root).resolve()
        self.commit = commit
        self.checked = set()
        self.code = []
        self.cohorts = []
        self.protocols = []
        self.excluded_audit_fields = set()

    def receipt(self, receipt, role):
        if role not in {'data', 'executed_code'}:
            raise ValueError('Missing or unsupported receipt role')
        if not isinstance(receipt, dict) or not {'path', 'sha256'} <= receipt.keys():
            raise ValueError('Malformed receipt')
        path = Path(receipt['path'])
        path = (path if path.is_absolute() else self.root / path).resolve()
        expected = receipt['sha256']
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError('Malformed SHA256')
        identity = (str(path), expected, role)
        if identity in self.checked:
            return path
        if role == 'executed_code':
            try:
                relative = path.relative_to(self.root)
            except ValueError as error:
                raise ValueError('Archived code is outside repository') from error
            if relative.suffix != '.py':
                raise ValueError('Unsupported archived code format')
            try:
                raw = subprocess.check_output(
                    ['git', '-C', str(self.root), 'show', f'{self.commit}:{relative.as_posix()}'],
                    stderr=subprocess.PIPE)
            except subprocess.CalledProcessError as error:
                raise ValueError('Code absent at specified archive: ' + str(relative)) from error
            if digest(raw) != expected:
                raise ValueError('Archive SHA mismatch at specified path: ' + str(relative))
            self.code.append({'path': str(relative), 'sha256': expected,
                              'commit': self.commit})
        else:
            if not path.is_file() or digest(path.read_bytes()) != expected:
                raise ValueError('Changed data artifact: ' + str(path))
        self.checked.add(identity)
        return path

    def receipts(self, value, role='data'):
        """Validate nested receipts, without implicitly opening their JSON files."""
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and 'sha256' in value:
                self.receipt(value, role)
            for key, item in value.items():
                if role == 'data' and 'audit' in key.lower():
                    self.excluded_audit_fields.add(key)
                    continue
                self.receipts(item, role)
        elif isinstance(value, list):
            for item in value:
                self.receipts(item, role)

    def source_inventory(self, protocol):
        if protocol.get('source_cohort_use') not in COHORT_USES:
            raise ValueError('Missing or unsupported source_cohort data-role declaration')
        path = self.receipt(protocol['source_cohort'], 'data')
        self.cohorts.append({'receipt': protocol['source_cohort'],
                             'role': 'source_snapshot_list_data_only',
                             'declaration': protocol['source_cohort_use']})
        # Read only the original snapshot paths/list. The old algorithm is data.
        old = read(path)
        source_rows = old.get('items', old.get('cases', []))
        paths = {}
        for row in source_rows:
            if not isinstance(row, dict) or not isinstance(row.get('source'), str):
                raise ValueError('Source cohort lacks declared snapshot rows')
            if paths.setdefault(row['case'], row['source']) != row['source']:
                raise ValueError('Ambiguous source snapshot')
        result = {}
        for row in protocol['cases']:
            case = row['case']
            if case in result or set(row['inputs']) != INPUTS:
                raise ValueError('Duplicate case or incomplete source inputs')
            if paths.get(case) != row['source']:
                raise ValueError('Source cohort path disagrees with case')
            self.receipts(row['inputs'])
            result[case] = {'source': row['source'], 'inputs': row['inputs']}
        if set(paths) != set(result):
            raise ValueError('Source cohort denominator changed')
        return result

    def execution(self, prepared_receipt, summary_receipt):
        prepared_path = self.receipt(prepared_receipt, 'data')
        summary_path = self.receipt(summary_receipt, 'data')
        protocol, summary = read(prepared_path), read(summary_path)
        version = protocol.get('version')
        if version not in NATIVE | {CHAIN, CODEC, GATE}:
            raise ValueError('No provenance roles for protocol version: ' + str(version))
        if summary.get('version') != version:
            raise ValueError('Protocol/summary version differs')
        self.protocols.append({'prepared': prepared_receipt, 'summary': summary_receipt,
                               'role': 'executed_component', 'version': version})
        if not protocol.get('algorithm'):
            raise ValueError('Executed protocol has no algorithm receipts')
        self.receipts(protocol['algorithm'], 'executed_code')
        if 'gate_implementation' in protocol:
            self.receipts(protocol['gate_implementation'], 'executed_code')
        self.receipts({k: v for k, v in protocol.items()
                       if k not in {'algorithm', 'gate_implementation'}})
        self.receipts(summary)
        cases = [row['case'] if isinstance(row, dict) else row for row in protocol['cases']]
        if not cases or len(cases) != len(set(cases)):
            raise ValueError('Empty or duplicate protocol cohort')
        expected_rows = ([item['case'] for item in protocol['items']]
                         if version in {CODEC, GATE} else cases)
        rows = summary.get('results' if version in NATIVE else 'decisions', [])
        index = complete_index(rows, expected_rows)
        denominator = summary.get('denominator', summary.get('trial_denominator'))
        if denominator != len(cases):
            raise ValueError('Summary denominator differs')
        sources = None
        if version in NATIVE:
            sources = self.source_inventory(protocol)
        elif version == CHAIN:
            components = protocol['components']
            if ([c['name'] for c in components] != protocol['precedence']
                    or set(summary['component_summaries']) != set(protocol['precedence'])):
                raise ValueError('Incomplete ordered execution components')
            for component in components:
                component_summary = summary['component_summaries'][component['name']]
                if component['source']['sha256'] != component['prepared']['sha256']:
                    raise ValueError('Copied component protocol changed')
                if ('replay_summary' in component and
                        component['replay_summary']['sha256'] != component_summary['sha256']):
                    raise ValueError('Replayed component summary changed')
                child = self.execution(component['prepared'], component_summary)
                if set(child['cases']) != set(cases):
                    raise ValueError('Executed component cohort differs')
                if child['sources'] is not None:
                    if sources is not None and sources != child['sources']:
                        raise ValueError('Executed components have different source hashes')
                    sources = child['sources']
            if sources is None:
                raise ValueError('Chain has no complete source inventory')
        elif version == CODEC:
            child = self.execution(protocol['semantic'], summary['source_summary'])
            if set(child['cases']) != set(cases):
                raise ValueError('Semantic replay cohort differs')
        return {'cases': cases, 'sources': sources, 'index': index, 'summary': summary}

    def report(self):
        return {'commit': self.commit, 'receipt_count': len(self.checked),
                'code_receipts': self.code, 'executed_protocols': self.protocols,
                'data_cohorts': self.cohorts,
                'excluded_audit_fields': sorted(self.excluded_audit_fields),
                'rule': 'Only declared execution edges expand. Data receipts are byte-verified; their algorithms are not executed dependencies.'}


def complete_index(rows, cases):
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('case'), str) or row['case'] in result:
            raise ValueError('Duplicate or malformed summary row')
        result[row['case']] = row
    if len(cases) != len(set(cases)) or set(result) != set(cases):
        raise ValueError('Summary does not cover the complete declared cohort')
    return result


def load_components(components):
    if [c['name'] for c in components] != list(ARCHIVES):
        raise ValueError('Require fixed round01 then declaration precedence')
    loaded, reports, sources = {}, {}, None
    for component in components:
        name = component['name']
        if component.get('commit') != ARCHIVES[name]:
            raise ValueError('Unexpected immutable component commit')
        verifier = Verifier(ROOT, component['commit'])
        seal_path = verifier.receipt(component['seal'], 'data')
        if read(seal_path) != component['prepared']:
            raise ValueError('Seal does not identify the supplied prepared protocol')
        result = verifier.execution(component['prepared'], component['summary'])
        expected_version = CHAIN if name == 'round01' else 'controlled-guest-declaration-order-search.v1'
        if result['summary']['version'] != expected_version:
            raise ValueError('Unexpected top-level component kind')
        if sources is not None and sources != result['sources']:
            raise ValueError('Components have different source cohorts or hashes')
        sources = result['sources']
        loaded[name], reports[name] = result, verifier.report()
    return loaded, reports, sources


def compose(cases, loaded):
    decisions = []
    for case in sorted(cases):
        row = {'case': case, 'branch': 'abstain', 'alert': None}
        for name in ARCHIVES:
            entry = loaded[name]['index'][case]
            if entry.get('alert'):
                row = {'case': case, 'branch': name, 'alert': entry['alert'],
                       'component_branch': entry.get('branch')}
                break
        decisions.append(row)
    return decisions


def prepare(args):
    components = []
    for name, directory in [('round01', args.round01), ('declaration', args.declaration)]:
        components.append({'name': name, 'commit': ARCHIVES[name],
                           **{key: frozen(Path(directory) / (key + '.json'))
                              for key in ('prepared', 'summary', 'seal')}})
    loaded, reports, sources = load_components(components)
    protocol = {'version': VERSION, 'precedence': list(ARCHIVES), 'components': components,
                'cases': sorted(sources), 'source_inventory': sources,
                'algorithm': frozen(__file__), 'provenance': reports,
                'retrospective': True, 'fresh_native_executions': 0, 'fresh_provider_calls': 0,
                'evaluation_labels_used': False,
                'policy': 'First existing alert in fixed component order. Never replace based on audit labels.',
                'created_utc': datetime.now(timezone.utc).isoformat()}
    Path(args.output).mkdir(parents=True, exist_ok=False)
    write(Path(args.output) / 'prepared.json', protocol)
    write(Path(args.output) / 'seal.json', frozen(Path(args.output) / 'prepared.json'))
    return {'trials': len(sources), 'prepared': frozen(Path(args.output) / 'prepared.json')}


def run(args):
    root = Path(args.input)
    verifier = Verifier(ROOT, ARCHIVES['round01'])
    seal = read(root / 'seal.json')
    if verifier.receipt(seal, 'data') != (root / 'prepared.json').resolve():
        raise ValueError('Chain seal points to a different prepared protocol')
    protocol = read(root / 'prepared.json')
    if protocol.get('version') != VERSION or protocol.get('precedence') != list(ARCHIVES):
        raise ValueError('Unexpected archived chain protocol')
    verifier.receipt(protocol['algorithm'], 'data')
    loaded, reports, sources = load_components(protocol['components'])
    if sources != protocol['source_inventory'] or sorted(sources) != protocol['cases']:
        raise ValueError('Frozen chain source inventory changed')
    if reports != protocol['provenance']:
        raise ValueError('Component provenance changed since preparation')
    if (root / 'summary.json').exists():
        if verifier.receipt(read(root / 'summary_seal.json'), 'data') != (root / 'summary.json').resolve():
            raise ValueError('Summary seal points to another artifact')
        return read(root / 'summary.json')
    decisions = compose(protocol['cases'], loaded)
    summary = {'version': VERSION, 'denominator': len(decisions), 'decisions': decisions,
               'alerts': [row for row in decisions if row['alert']],
               'component_summaries': {c['name']: c['summary'] for c in protocol['components']},
               'fresh_native_executions': 0, 'fresh_provider_calls': 0,
               'historical_native_executions': {
                   name: item['summary'].get('native_executions', item['summary'].get('replayed_native_executions', 0))
                   for name, item in loaded.items()},
               'retrospective': True, 'evaluation_labels_used': False,
               'independent_audit_complete': False,
               'completed_utc': datetime.now(timezone.utc).isoformat()}
    write(root / 'summary.json', summary)
    write(root / 'summary_seal.json', frozen(root / 'summary.json'))
    return {'alerts': len(summary['alerts']), 'denominator': summary['denominator'],
            'fresh_native_executions': 0, 'fresh_provider_calls': 0, 'retrospective': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--round01', type=Path)
    parser.add_argument('--declaration', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    if args.stage == 'prepare' and any(getattr(args, k) is None for k in ('round01', 'declaration', 'output')):
        parser.error('prepare requires --round01, --declaration and --output')
    if args.stage == 'run' and args.input is None:
        parser.error('run requires --input')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
