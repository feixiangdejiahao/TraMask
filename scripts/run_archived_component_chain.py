"""Replay complete archived summaries in a supplied, frozen component order.

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
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import archived_absence_null_validation as gated_native

VERSION = 'archived-complete-component-chain.v3'
ARCHIVED = 'archived-complete-component-chain.v1'
ARCHIVES = {ARCHIVED, 'archived-complete-component-chain.v2', VERSION}
SEQUENTIAL = 'sequential-source-admission.v1'
QUANTITY = 'controlled-quantity-bound-search.v1'
CHAIN = 'ordered-source-relation-exact-semantic-chain.v4'
CODEC = 'codec-guarded-exact-semantic-replay.v2'
GATE = 'exact-payload-second-gate-replay.v1'
NATIVE = {
    QUANTITY,
    'documented-default-search.v1',
    'controlled-guest-carrier-inverse-search.v1',
    'controlled-http-error-finalization-search.v1',
    'controlled-guest-declaration-order-search.v1',
}
SEMANTIC_INPUTS = {'corpus.json', 'frontend.json', 'issue.md'}
ATTEMPT_ARTIFACTS = {
    'selection.json', 'inventory.json', 'dispatch_claim.json',
    'admission/prepared.json', 'admission/summary.json',
    'admission/source_context/context_0000.json',
    'admission/item_0000/analysis.json', 'admission/item_0000/request.json',
    'admission/item_0000/decision.json',
    *{'admission/item_0000/completion/' + name for name in
      ('completion.txt', 'manifest.json', 'request.json', 'response.body', 'response.json')},
}
COHORT_USES = {
    'Trial list and original source paths only; no candidates or outcomes.',
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
    def __init__(self, root, commit, *, code_root=None):
        self.root = Path(root).resolve()
        self.code_root = self.root if code_root is None else Path(code_root).resolve()
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise ValueError('Archive must be an immutable full commit')
        try:
            self.code_root.relative_to(self.root)
        except ValueError as error:
            raise ValueError('Code worktree is outside repository workspace') from error
        self.commit = commit
        self.checked = set()
        self.code = []
        self.cohorts = []
        self.protocols = []
        self.excluded_audit_fields = set()
        self.dependencies = []
        if self.code_root != self.root:
            top = subprocess.check_output(['git', '-C', str(self.code_root), 'rev-parse', '--show-toplevel']).decode().strip()
            head = subprocess.check_output(['git', '-C', str(self.code_root), 'rev-parse', 'HEAD']).decode().strip()
            if Path(top).resolve() != self.code_root or head != commit:
                raise ValueError('Frozen worktree root or HEAD differs from archive')

    def receipt(self, receipt, role):
        if role not in {'data', 'executed_code'}:
            raise ValueError('Missing or unsupported receipt role')
        if not isinstance(receipt, dict) or not {'path', 'sha256'} <= receipt.keys():
            raise ValueError('Malformed receipt')
        path = Path(receipt['path'])
        path = (path if path.is_absolute() else self.root / path).resolve()
        expected = receipt['sha256']
        if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
            raise ValueError('Malformed SHA256')
        identity = (str(path), expected, role)
        if identity in self.checked:
            return path
        if role == 'executed_code':
            try:
                relative = path.relative_to(self.code_root)
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
            if self.code_root != self.root and (not path.is_file() or digest(path.read_bytes()) != expected):
                raise ValueError('Frozen worktree code SHA mismatch: ' + str(relative))
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
        construction_inputs = INPUTS | {'relation_ir'} if protocol['version'] == QUANTITY else INPUTS
        for row in protocol['cases']:
            case = row['case']
            if case in result or set(row['inputs']) != construction_inputs:
                raise ValueError('Duplicate case or incomplete source inputs')
            if paths.get(case) != row['source']:
                raise ValueError('Source cohort path disagrees with case')
            self.receipts(row['inputs'])
            result[case] = {'source': row['source'],
                            'inputs': {key: value for key, value in row['inputs'].items() if key in INPUTS}}
            if protocol['version'] == QUANTITY:
                self.dependencies.append(dict(role='relation_construction_data', case=case,
                    receipt=row['inputs']['relation_ir'],
                    provider_discovery_verified=False,
                    reason='Native protocol freezes relation bytes but does not declare their discovery protocol.'))
        if set(paths) != set(result):
            raise ValueError('Source cohort denominator changed')
        return result

    def sequential_inventory(self, protocol):
        """Read the queue inventory as frozen candidate/source data only."""
        inventory = read(self.receipt(protocol['inventory'], 'data'))
        if inventory.get('source_inventory') != protocol['source_inventory']:
            raise ValueError('Sequential inventory source receipt differs')
        self.receipt(protocol['source_inventory'], 'data')
        source_receipts = {str(self.receipt(row, 'data')): row for row in protocol['source_inputs']}
        records, sources = {}, {}
        for row in inventory['controlled_failures']:
            key = row['key']
            if key in records:
                raise ValueError('Duplicate sequential candidate occurrence')
            if set(row['inputs']) != {'corpus', 'frontend', 'candidates', 'runs'}:
                raise ValueError('Unknown sequential source-input roles')
            self.receipts(row['inputs'])
            original = Path(row['inputs']['corpus']['path']).resolve().parent
            inputs = {name + '.json': row['inputs'][name] for name in ('corpus', 'frontend')}
            issue = source_receipts.get(str(original / 'issue.md'))
            if issue is None:
                raise ValueError('Sequential issue has no frozen source receipt')
            inputs['issue.md'] = issue
            for name, value in inputs.items():
                if Path(value['path']).resolve() != original / name or source_receipts.get(str(original / name)) != value:
                    raise ValueError('Sequential source path or receipt disagrees')
            source = dict(source=str(original), inputs=inputs)
            if row['case'] in sources and sources[row['case']] != source:
                raise ValueError('Sequential candidates use different source snapshots')
            sources[row['case']] = source
            records[key] = row
        ranked = []
        for case in protocol['cases']:
            ranking = case['ranking']
            if [row['rank'] for row in ranking] != list(range(1, len(ranking)+1)):
                raise ValueError('Sequential ranking is not contiguous')
            if len({row['candidate_id'] for row in ranking}) != len(ranking):
                raise ValueError('Sequential candidate ranking is duplicated')
            for row in ranking:
                record = records.get(row['key'])
                if record is None or (record['case'], record['candidate_id']) != (case['case'], row['candidate_id']):
                    raise ValueError('Sequential ranking differs from source occurrence')
                ranked.append(row['key'])
        if len(ranked) != len(set(ranked)) or set(ranked) != set(records) or set(sources) != {c['case'] for c in protocol['cases']}:
            raise ValueError('Sequential ranking omits a source occurrence or case')
        self.dependencies.append(dict(role='controlled_candidate_inventory_data_only', receipt=protocol['inventory'],
            source_inventory=protocol['source_inventory'], source_inputs=protocol['source_inputs'],
            expanded_baseline_algorithm=False, frozen_semantic_inputs=sorted(SEMANTIC_INPUTS),
            unrecorded_metadata=['case.json', 'selection.json']))
        return records, sources

    def sequential_attempt(self, directory, result_receipt, protocol, record, expected):
        """Open only the explicit single-admission and reused-evidence edges."""
        directory = Path(directory).resolve()
        if self.receipt(result_receipt, 'data') != directory / 'result.json':
            raise ValueError('Sequential result path differs from its ordinal')
        result = read(result_receipt['path'])
        artifacts = result.get('artifacts')
        if not isinstance(artifacts, dict) or not set(artifacts) <= ATTEMPT_ARTIFACTS:
            raise ValueError('Unknown sequential attempt artifact type')
        actual = {str(path.relative_to(directory)) for path in directory.rglob('*')
                  if path.is_file() and path != directory / 'result.json'}
        if actual != set(artifacts):
            raise ValueError('Sequential attempt artifact inventory differs')
        for path, expected_hash in artifacts.items():
            self.receipt(dict(path=str(directory / path), sha256=expected_hash), 'data')
        if 'selection.json' not in artifacts or read(directory / 'selection.json') != expected or result['selection'] != expected:
            raise ValueError('Sequential attempt differs from frozen round-robin selection')
        if result['outcome'] != admission_outcome(result['decision']):
            raise ValueError('Sequential outcome differs from its admission decision')
        for key in ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing'):
            if type(result.get(key)) is not int or result[key] < 0:
                raise ValueError('Invalid sequential attempt accounting')
        if 'inventory.json' in artifacts:
            inventory = read(directory / 'inventory.json')
            if (inventory.get('controlled_failures') != [record]
                    or inventory.get('source_inventory') != protocol['source_inventory']):
                raise ValueError('Single-admission inventory differs from ranked occurrence')
        if 'admission/prepared.json' not in artifacts:
            if result['outcome'] != 'unknown' or result['provider_calls']:
                raise ValueError('Unprepared attempt cannot provide a semantic result')
        else:
            self.admission_artifacts(directory, artifacts, result, protocol, record)
        # Reused native evidence is an explicit data edge, never a new run.
        self.receipts(record['native_evidence'])
        for evidence in record['native_evidence']:
            if not {'result', 'manifest', 'test_ids', 'tests'} <= set(evidence):
                raise ValueError('Unknown reused-native evidence shape')
            manifest = read(evidence['manifest']['path'])
            for mount in manifest.get('mounts', []):
                self.receipt(dict(path=mount['source'], sha256=mount['sha256']), 'data')
        self.dependencies.append(dict(role='sequential_admission_attempt', selection=expected,
            result=result_receipt, artifact_hashes=artifacts,
            reused_native_evidence=record['native_evidence'], fresh_native_executions=0))
        return result

    def admission_artifacts(self, directory, artifacts, result, protocol, record):
        prepared_path = directory / 'admission/prepared.json'
        prepared = read(prepared_path)
        if (prepared.get('stage') != 'prepared'
                or prepared.get('experiment') != 'incremental_admission_of_frozen_generated_tests'
                or prepared.get('method') != 'compact_contract_guarded'
                or prepared.get('method_module') != 'relation_search.compact_contract_guarded'
                or prepared.get('request_identity_version') != 'actual-admission-dispatch-fields-v1'):
            raise ValueError('Unsupported single-admission artifact type')
        expected_algorithm = {str(Path(row['path']).resolve().relative_to(self.code_root)): row['sha256']
                              for row in protocol['algorithm'].values()}
        if prepared.get('algorithm') != expected_algorithm:
            raise ValueError('Admission algorithm differs from frozen queue algorithm')
        if (prepared.get('imported_source_modules') != protocol['algorithm']
                or prepared.get('algorithm_entry_modules') != {
                    prepared['method_module']: protocol['algorithm'][prepared['method_module']]}):
            raise ValueError('Admission executed module roles differ from queue algorithm')
        for path, sha in prepared['algorithm'].items():
            self.receipt(dict(path=str(self.code_root / path), sha256=sha), 'executed_code')
        for key in ('algorithm_entry_modules', 'imported_source_modules'):
            self.receipts(prepared[key], 'executed_code')
        self.receipts({key: value for key, value in prepared.items()
                       if key not in {'algorithm', 'algorithm_entry_modules', 'imported_source_modules'}})
        if prepared['baseline'] != dict(path=str(directory / 'inventory.json'), sha256=artifacts.get('inventory.json')):
            raise ValueError('Admission baseline is not the selected occurrence')
        if len(prepared.get('items', [])) != 1:
            raise ValueError('Admission must contain exactly one item')
        item = prepared['items'][0]
        if any(item.get(key) != result['selection'][key] for key in ('key', 'case', 'candidate_id')):
            raise ValueError('Admission item differs from selected occurrence')
        if item['name'] != 'item_0000' or item['source_inputs'] != record['inputs']:
            raise ValueError('Admission item source inputs differ')
        for key, relative in [('analysis_path', 'admission/item_0000/analysis.json'),
                              ('request_path', 'admission/item_0000/request.json')]:
            value = item.get(key)
            if value is not None and (Path(value).resolve() != directory / relative or relative not in artifacts):
                raise ValueError('Admission item artifact path differs')
        if item.get('request_path') and item.get('request_sha256') != artifacts['admission/item_0000/request.json']:
            raise ValueError('Admission request SHA differs')
        if 'dispatch_claim.json' in artifacts:
            claim = read(directory / 'dispatch_claim.json')
            if (not item.get('request_path') or claim.get('reserved_calls') != 1
                    or claim.get('request') != dict(path=item['request_path'], sha256=item['request_sha256'])):
                raise ValueError('Dispatch claim differs from the prepared request')
            self.receipts(claim)
        completion_prefix = 'admission/item_0000/completion/'
        if completion_prefix + 'manifest.json' in artifacts:
            if 'dispatch_claim.json' not in artifacts:
                raise ValueError('Provider completion has no dispatch claim')
            completion = read(directory / (completion_prefix + 'manifest.json'))
            request = read(item['request_path'])
            if (completion.get('request_id') != request.get('id')
                    or result['decision'].get('request_id') != request.get('id')):
                raise ValueError('Provider request identity differs from recorded outcome')
            for key, filename in [('request_sha256', 'request.json'), ('response_sha256', 'response.body')]:
                if completion.get(key) != artifacts.get(completion_prefix + filename):
                    raise ValueError('Provider raw request or response SHA differs')
        if 'admission/summary.json' not in artifacts:
            if result['outcome'] != 'unknown' or result['provider_calls']:
                raise ValueError('Incomplete admission cannot provide a semantic result')
            return
        summary = read(directory / 'admission/summary.json')
        if (summary.get('stage') != 'complete' or summary.get('prepared') != frozen(prepared_path)
                or len(summary.get('decisions', [])) != 1):
            raise ValueError('Incomplete or changed single-admission summary')
        row = summary['decisions'][0]
        if (any(row.get(key) != result['selection'][key] for key in ('key', 'case', 'candidate_id'))
                or row['decision'] != result['decision']):
            raise ValueError('Admission summary differs from recorded outcome')
        decision_path = directory / 'admission/item_0000/decision.json'
        if (row.get('decision_path') != str(decision_path) or 'admission/item_0000/decision.json' not in artifacts
                or read(decision_path) != result['decision']):
            raise ValueError('Raw admission decision differs from recorded outcome')
        if summary['provider_calls'] != result['provider_calls']:
            raise ValueError('Admission provider accounting differs')

    def sequential(self, protocol, summary, prepared_receipt, output):
        if (summary.get('stage') != 'complete' or summary.get('prepared') != prepared_receipt
                or protocol['policy'].get('method') != 'compact_contract_guarded'
                or protocol['policy'].get('ordering') != 'sorted_cases_round_robin_source_rank'
                or protocol['policy'].get('stop') != 'first_semantic_supported_per_case'):
            raise ValueError('Unsupported or incomplete sequential execution policy')
        records, sources = self.sequential_inventory(protocol)
        cases = protocol['cases']
        names = [case['case'] for case in cases]
        if names != sorted(names):
            raise ValueError('Sequential cohort is not sorted')
        attempt_receipts = summary['attempt_receipts']
        if summary.get('attempts') != len(attempt_receipts):
            raise ValueError('Sequential attempt count differs')
        directories = sorted((output / 'attempts').iterdir()) if (output / 'attempts').exists() else []
        expected_directories = [output / 'attempts' / f'attempt_{i:06d}' for i in range(len(attempt_receipts))]
        if directories != expected_directories or any(not path.is_dir() for path in directories):
            raise ValueError('Sequential attempt trace is incomplete or noncontiguous')
        results = []
        for directory, result_receipt in zip(directories, attempt_receipts):
            expected = next_selection(cases, results, protocol['policy']['max_per_case'])
            if expected is None:
                raise ValueError('Sequential trace continued after its stopping rule')
            results.append(self.sequential_attempt(directory, result_receipt, protocol, records[expected['key']], expected))
        outputs = [dict(**row['selection'], decision=row['decision']) for row in results if row['outcome'] == 'supported']
        if summary.get('outputs') != outputs:
            raise ValueError('Sequential outputs differ from first supported outcomes')
        counts = {name: sum(row['outcome'] == name for row in results) for name in ('unknown', 'rejected', 'supported')}
        counts['pending'] = sum(len(case['ranking']) for case in cases) - len(results)
        if summary.get('counts') != counts:
            raise ValueError('Sequential outcome counts differ')
        totals = {key: sum(row[key] for row in results) for key in
                  ('provider_calls', 'reserved_calls', 'measured_tokens', 'reserved_tokens', 'usage_missing')}
        totals.update(accounted_calls=totals['provider_calls']+totals['reserved_calls'],
                      accounted_tokens=totals['measured_tokens']+totals['reserved_tokens'])
        if any(summary.get(key) != value for key, value in totals.items()) or summary.get('native_executions') != 0:
            raise ValueError('Sequential accounting differs from immutable attempts')
        index = {name: dict(case=name, alert=None) for name in names}
        for row in outputs:
            index[row['case']]['alert'] = dict(row, native_occurrence=records[row['key']],
                semantic_validity='unconfirmed; source-supported output is not an independent oracle audit')
        return dict(cases=names, sources=sources, index=index, summary=summary)

    def execution(self, prepared_receipt, summary_receipt):
        prepared_path = self.receipt(prepared_receipt, 'data')
        summary_path = self.receipt(summary_receipt, 'data')
        protocol, summary = read(prepared_path), read(summary_path)
        version = protocol.get('version')
        if version not in NATIVE | ARCHIVES | {CHAIN, CODEC, GATE, SEQUENTIAL, gated_native.VERSION}:
            raise ValueError('No provenance roles for protocol version: ' + str(version))
        if summary.get('version') != version:
            raise ValueError('Protocol/summary version differs')
        if version == SEQUENTIAL and summary.get('stage') != 'complete':
            raise ValueError('Sequential summary is not complete')
        self.protocols.append({'prepared': prepared_receipt, 'summary': summary_receipt,
                               'role': 'executed_component', 'version': version})
        if not protocol.get('algorithm'):
            raise ValueError('Executed protocol has no algorithm receipts')
        self.receipts(protocol['algorithm'], 'executed_code')
        if 'gate_implementation' in protocol:
            self.receipts(protocol['gate_implementation'], 'executed_code')
        derived_fields = {'provenance'} if version in ARCHIVES else set()
        self.receipts({k: v for k, v in protocol.items()
                       if k not in {'algorithm', 'gate_implementation'} | derived_fields})
        if derived_fields:
            self.dependencies.append(dict(role='prior_verification_report_data_only',
                container=prepared_receipt, fields=sorted(derived_fields),
                reason='The complete protocol bytes are sealed. Recompute declared execution edges; the old derived report is not execution authority.'))
        self.receipts(summary)
        cases = [row['case'] if isinstance(row, dict) else row for row in protocol['cases']]
        if not cases or len(cases) != len(set(cases)):
            raise ValueError('Empty or duplicate protocol cohort')
        if version == SEQUENTIAL:
            return self.sequential(protocol, summary, prepared_receipt, prepared_path.parent)
        if version == gated_native.VERSION:
            return gated_native.validate(self, protocol, summary, prepared_receipt, prepared_path.parent)
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
        elif version in ARCHIVES:
            components = protocol['components']
            names = component_names(components)
            if (protocol['precedence'] != names
                    or set(summary['component_summaries']) != set(names)):
                raise ValueError('Unsupported archived execution-edge order')
            loaded = {}
            for component in components:
                name = component['name']
                if 'prerequisite' in component:
                    raise ValueError('Unsupported prerequisite kind')
                if summary['component_summaries'][name] != component['summary']:
                    raise ValueError('Archived child summary changed')
                child_verifier = Verifier(self.root, component['commit'],
                    code_root=self.root / component.get('code_root', '.'))
                seal = read(child_verifier.receipt(component['seal'], 'data'))
                child_protocol = read(component['prepared']['path'])
                expected_seal = ({'prepared': component['prepared']}
                    if child_protocol.get('version') == SEQUENTIAL else component['prepared'])
                if seal != expected_seal:
                    raise ValueError('Archived child seal changed')
                child = child_verifier.execution(component['prepared'], component['summary'])
                if set(child['cases']) != set(cases):
                    raise ValueError('Archived child cohort differs')
                sources = merge_sources(sources, child['sources'])
                loaded[name] = child
                self.dependencies.append(dict(role='archived_executed_component', name=name,
                    prepared=component['prepared'], summary=component['summary'], verifier=child_verifier.report()))
            if sources != protocol['source_inventory'] or summary['decisions'] != compose(cases, loaded):
                raise ValueError('Archived chain decision or source inventory differs')
        return {'cases': cases, 'sources': sources, 'index': index, 'summary': summary}

    def report(self):
        return {'commit': self.commit, 'receipt_count': len(self.checked),
                'code_root': str(self.code_root), 'typed_dependencies': self.dependencies,
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


def admission_outcome(decision):
    if decision.get('status') == 'semantic_supported' and decision.get('alarm_eligible') is True:
        return 'supported'
    return 'rejected' if decision.get('status') == 'semantic_rejected' else 'unknown'


def next_selection(cases, results, maximum):
    counts = {case['case']: sum(row['selection']['case'] == case['case'] for row in results) for case in cases}
    solved = {row['selection']['case'] for row in results if row['outcome'] == 'supported'}
    names = [case['case'] for case in cases]
    start = (names.index(results[-1]['selection']['case'])+1) % len(names) if results and names else 0
    for offset in range(len(names)):
        case = cases[(start+offset) % len(names)]
        count = counts[case['case']]
        if case['case'] not in solved and count < min(maximum, len(case['ranking'])):
            return dict(case=case['case'], **case['ranking'][count])
    return None


def merge_sources(first, second):
    if first is None:
        return second
    if second is None or set(first) != set(second):
        raise ValueError('Components have different source cohorts or hashes')
    merged = {}
    for case in first:
        left, right = first[case], second[case]
        shared = set(left['inputs']) & set(right['inputs'])
        if (left['source'] != right['source'] or not SEMANTIC_INPUTS <= shared
                or set(left['inputs']) not in (INPUTS, SEMANTIC_INPUTS)
                or set(right['inputs']) not in (INPUTS, SEMANTIC_INPUTS)
                or any(left['inputs'][key] != right['inputs'][key] for key in shared)):
            raise ValueError('Components have different source cohorts or hashes')
        merged[case] = dict(source=left['source'], inputs={**left['inputs'], **right['inputs']})
    return merged


def component_names(components):
    required = {'name', 'commit', 'prepared', 'summary', 'seal'}
    if not isinstance(components, list) or not components:
        raise ValueError('Require a nonempty ordered component list')
    names = []
    for component in components:
        if (not isinstance(component, dict) or not required <= component.keys()
                or set(component) - required - {'code_root', 'prerequisite'}
                or not isinstance(component['name'], str) or not component['name']):
            raise ValueError('Unknown or malformed component declaration')
        names.append(component['name'])
    if len(names) != len(set(names)):
        raise ValueError('Duplicate component name')
    return names


def load_components(components):
    component_names(components)
    loaded, reports, sources = {}, {}, None
    for component in components:
        name = component['name']
        code_root = (ROOT / component.get('code_root', '.')).resolve()
        verifier = Verifier(ROOT, component['commit'], code_root=code_root)
        protocol = read(verifier.receipt(component['prepared'], 'data'))
        seal_path = verifier.receipt(component['seal'], 'data')
        seal = read(seal_path)
        expected_seal = {'prepared': component['prepared']} if protocol.get('version') == SEQUENTIAL else component['prepared']
        if seal != expected_seal:
            raise ValueError('Seal does not identify the supplied prepared protocol')
        result = verifier.execution(component['prepared'], component['summary'])
        if 'prerequisite' in component:
            raise ValueError('Unsupported prerequisite kind')
        if result['sources'] is None:
            raise ValueError('Component has no complete original source inventory')
        sources = merge_sources(sources, result['sources'])
        loaded[name], reports[name] = result, verifier.report()
    return loaded, reports, sources


def compose(cases, loaded, *, precedence=None):
    decisions = []
    for case in sorted(cases):
        row = {'case': case, 'branch': 'abstain', 'alert': None}
        for name in (loaded if precedence is None else precedence):
            entry = loaded[name]['index'][case]
            if entry.get('alert'):
                row = {'case': case, 'branch': name, 'alert': entry['alert'],
                       'component_branch': entry.get('branch')}
                break
        decisions.append(row)
    return decisions


def verification_algorithm():
    """Freeze every loaded local module used by the read-only verifier."""
    return {name: frozen(module.__file__) for name, module in sorted(sys.modules.items())
            if getattr(module, '__file__', None)
            and Path(module.__file__).suffix == '.py'
            and Path(module.__file__).resolve().is_relative_to(Path(__file__).resolve().parents[1])
            and not any(part in {'.venv', 'tests'} for part in Path(module.__file__).parts)}


def prepare(args):
    components = read(args.components)
    names = component_names(components)
    loaded, reports, sources = load_components(components)
    protocol = {'version': VERSION, 'precedence': names, 'components': components,
                'components_spec': frozen(args.components),
                'cases': sorted(sources), 'source_inventory': sources,
                'algorithm': verification_algorithm(), 'provenance': reports,
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
    protocol = read(root / 'prepared.json')
    names = component_names(protocol['components'])
    verifier = Verifier(ROOT, protocol['components'][0]['commit'])
    seal = read(root / 'seal.json')
    if verifier.receipt(seal, 'data') != (root / 'prepared.json').resolve():
        raise ValueError('Chain seal points to a different prepared protocol')
    if protocol.get('version') != VERSION or protocol.get('precedence') != names:
        raise ValueError('Unexpected archived chain protocol')
    if read(verifier.receipt(protocol['components_spec'], 'data')) != protocol['components']:
        raise ValueError('Frozen component specification differs')
    verifier.receipts(protocol['algorithm'], 'data')
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
               'component_outputs': {name: [item['index'][case] for case in sorted(item['index'])]
                                     for name, item in loaded.items()},
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
    parser.add_argument('--components', type=Path, help='Ordered JSON list of exact component receipts and archive commits')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    args = parser.parse_args()
    if args.stage == 'prepare' and (args.components is None or args.output is None):
        parser.error('prepare requires --components and --output')
    if args.stage == 'run' and args.input is None:
        parser.error('run requires --input')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
