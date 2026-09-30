"""Independently audit sealed source-failure JSON, source bytes and graph paths.

No census/analyser code is imported or run. This verifies transport integrity,
not the analyser's semantic soundness, a complete oracle or test execution.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def audit_member(original, candidate, test_owner, result, counts):
    """Apply sealed input edits and check evidence without using its emitter."""
    current = dict(original)
    edits = sorted(candidate.get('edits', []),
        key=lambda e: (e['span']['start_byte'], e['span']['end_byte']))
    previous = -1
    for edit in edits:
        extent = edit['span']
        require(extent['path'] == test_owner, 'candidate edit is outside owner file')
        require(extent['start_byte'] >= previous, 'candidate edits overlap')
        previous = extent['end_byte']
        require(original[test_owner][extent['start_byte']:extent['end_byte']].decode() == edit['before'],
            'candidate edit differs from original source')
    for edit in reversed(edits):
        extent = edit['span']
        current[test_owner] = (current[test_owner][:extent['start_byte']] + edit['after'].encode()
            + current[test_owner][extent['end_byte']:])

    def at(extent, code=None, data=current):
        raw = data[extent['path']]
        require(0 <= extent['start_byte'] <= extent['end_byte'] <= len(raw), 'span outside source')
        value = raw[extent['start_byte']:extent['end_byte']].decode()
        require(code is None or value == code, 'code differs from exact source span')
        counts['source_extents_verified'] += 1
        return value

    statuses, unknowns, shapes = Counter(), {}, {}
    for call in result['calls']:
        counts['call_sites'] += 1
        counts['instances'] += len(call['instances'])
        at(call['span'], call['code'])
        binding = call['binding']
        require(binding['status'] == 'source_bound', 'selected call is not source bound')
        at(binding['import_span'], binding['import_code'])
        code = at(binding['declaration_span'], binding['declaration_code'])
        require(hashlib.sha256(code.encode()).hexdigest() == binding['declaration_sha256'], 'declaration SHA mismatch')
        require(hashlib.sha256(current[binding['declaration_span']['path']]).hexdigest()
            == binding['declaration_source_sha256'], 'declaration source SHA mismatch')
        for mapping in binding['actual_formal']:
            at(mapping['formal']['span'], mapping['formal']['name'])
            for actual in mapping['actuals']:
                at(actual['span'], actual['code'])
        evidence = call['failure_evidence']
        function = evidence['function']
        require(evidence['can_reach_failure'], 'selected call lacks failure evidence')
        require(call['expected_port_status'] == 'unknown', 'source support was promoted to an expected port')
        counts['reachable_calls'] += 1
        for row in evidence['reachable_functions']:
            at(row['span'], row['code'], original)
            require(hashlib.sha256(original[row['span']['path']]).hexdigest() == row['source_sha256'],
                'failure function source SHA mismatch')
            statuses[row['status']] += 1
            for formal in row['parameters']:
                at(formal['span'], formal['name'], original)
        canonical = {row['id']: row for row in evidence['same_package_calls']}
        require(len(canonical) == len(evidence['same_package_calls']), 'duplicate canonical call ID')
        for row in evidence['same_package_calls'] + evidence['sink_evidence']:
            at(row['span'], row['code'], original)
            for mapping in row.get('actual_formal', []):
                at(mapping['formal']['span'], mapping['formal']['name'], original)
                for actual in mapping['actuals']:
                    at(actual['span'], actual['code'], original)
            for actual in row.get('diagnostic_arguments', []):
                at(actual['span'], actual['code'], original)
        for condition in evidence['conditions']:
            at(condition['branch_span'], data=original)
            for expression in [condition.get('expression'), *condition['operands'], *condition['case_patterns']]:
                if expression:
                    at(expression['span'], expression['code'], original)
        sinks = {row['call_id'] for row in evidence['sink_evidence']}
        require(bool(evidence['shortest_failure_paths']), 'failure evidence has no path witness')
        for path in evidence['shortest_failure_paths']:
            require(bool(path), 'empty failure path')
            parent = function['id']
            for index, step in enumerate(path):
                require(step == canonical.get(step['id']), 'path differs from canonical source call')
                require(step['caller_id'] == parent, 'path caller/target discontinuity')
                if index == len(path) - 1:
                    require(step['id'] in sinks and step['status'] == 'testing_sink', 'path lacks confirmed sink endpoint')
                else:
                    require(step['status'] == 'same_package_static_call', 'unproved dispatch in failure path')
                    parent = step['target_id']
            counts['failure_paths_verified'] += 1
        require(bool(evidence['limits']), 'analysis limitations missing')
        key = str((binding['module'], binding['declaration_sha256']))
        unknowns[key] = dict(Counter(row['reason'] for row in evidence['unknowns']))
        shapes[key] = dict(entry_name=binding['declaration_name'],
            reachable_functions=len(evidence['reachable_functions']),
            partial_unknown_reachable_functions=sum(row['status'] == 'partial_unknown' for row in evidence['reachable_functions']),
            conditions=len(evidence['conditions']),
            paths=[[function['name'], *[step['callee'] for step in path]] for path in evidence['shortest_failure_paths']])
    return statuses, unknowns, shapes


def audit(input_path):
    protocol, seal = read(input_path/'protocol.json'), read(input_path/'seal.json')
    for name, expected in seal['files_sha256'].items():
        require(sha(input_path/name) == expected, 'sealed output SHA mismatch: ' + name)
    for name, expected in protocol['inputs_sha256'].items():
        require(sha(name) == expected, 'sealed input SHA mismatch: ' + name)
    # Historical code is verified in the sealed snapshot, not the live tree.
    for name, expected in protocol['code_sha256'].items():
        require(sha(input_path/'code_snapshot'/name) == expected, 'code snapshot SHA mismatch: ' + name)
    paired = Path(protocol['paired'])
    inventory = Path(read(paired/'protocol.json')['inventory'])
    ready = read(paired/'ready.json')
    counts, statuses, unknowns, shapes = Counter(), Counter(), {}, {}
    for record in ready['records']:
        require(record['status'] == 'offerable', 'non-offerable record is outside this sealed cohort')
        request = read(record['arms']['template']['request'])
        corpus = read(inventory/record['case']/'corpus.json')
        original = {path: row['code'].encode() for path, row in corpus['sources'].items()}
        require([row['candidate']['id'] for row in request['offered'].values()] == record['member_ids'], 'member cohort mismatch')
        for alias, offered in request['offered'].items():
            result = read(input_path/record['case']/(alias+'.json'))
            require(result['candidate_id'] == offered['candidate']['id'], 'candidate identity mismatch')
            counts['members'] += 1
            owner = corpus['tests'][offered['candidate']['base_test_id']]['span']['path']
            per_status, per_unknown, per_shape = audit_member(original, offered['candidate'], owner, result, counts)
            statuses.update(per_status)
            unknowns.update(per_unknown)
            shapes.update(per_shape)
    summary = read(input_path/'summary.json')
    require(counts['members'] == summary['totals']['members'], 'member denominator mismatch')
    require(counts['call_sites'] == summary['totals']['unproved_call_sites'], 'call denominator mismatch')
    require(counts['instances'] == summary['totals']['unproved_instances'], 'instance denominator mismatch')
    return dict(version='source-failure-independent-audit-v2', status='independently_verified',
        census_seal_sha256=sha(input_path/'seal.json'), summary_sha256=sha(input_path/'summary.json'),
        protocol_sha256=sha(input_path/'protocol.json'), all_sealed_files_verified=len(seal['files_sha256']),
        all_input_sha_verified=len(protocol['inputs_sha256']), all_code_sha_verified=len(protocol['code_sha256']),
        counts=dict(counts), transported_function_status_instances=dict(statuses),
        unique_api_unknowns=unknowns, unique_api_shapes=shapes, provider_calls=0, subject_executions=0,
        limits='Independent JSON/span/SHA/path checks only. No census audit function or analyser is imported; binding and failure semantics are not independently inferred. May reachability is not an oracle contract, safe edit or execution proof.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'audit output already exists')
    auditor_sha = sha(__file__)
    result = dict(audit(args.input), auditor_sha256=auditor_sha)
    require(sha(__file__) == auditor_sha, 'auditor changed during run')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        stream.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps(result['counts'], sort_keys=True))
