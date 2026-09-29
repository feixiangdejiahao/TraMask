"""Compare all frozen overlay groups by proven source q, without target labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write
from scripts.audit_observed_write_feedback import canonical, observation_key
import json


def writer(event):
    return [event.get('source_last_observed_writer'),
            event.get('source_last_observed_writer_sha256')]


def valid(event):
    return (event['status'] == 'observed_within_instrumented_code'
            and event.get('source_q_span') and event.get('source_allocation_span')
            and event.get('source_last_observed_writer'))


def compare_group(group):
    tables = {role: defaultdict(list) for role in ['control', 'generated']}
    reads = Counter()
    roles = defaultdict(Counter)
    fields = defaultdict(Counter)
    unknown = []
    evidence = {}
    for phase in group['phases']:
        role = phase['role']
        path = Path(group['execution']) / role / 'observed_writes.jsonl'
        if not path.is_file():
            if phase['observed_reads']:
                raise ValueError('Missing trace containing reported reads')
            continue
        checksum = digest(path)
        evidence[str(path.resolve())] = checksum
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            event = json.loads(line)
            if event['kind'] != 'assertion_read':
                continue
            status = 'valid_mapped' if valid(event) else 'unknown_or_unmapped'
            reads[status] += 1
            roles[role][status] += 1
            fields[event['field']][status] += 1
            located = dict(trace=str(path.resolve()), trace_sha256=checksum,
                           trace_line=lineno, event=event)
            if status != 'valid_mapped':
                unknown.append(located)
            if role in tables and event.get('source_q_span'):
                tables[role][canonical(observation_key(event))].append(located)
    comparisons = []
    for key in sorted(tables['control'].keys() & tables['generated'].keys()):
        control = tables['control'][key]
        generated = tables['generated'][key]
        a = [r for r in control if valid(r['event'])]
        b = [r for r in generated if valid(r['event'])]
        comparable = bool(a and b)
        old_writers = {canonical(writer(r['event'])) for r in a}
        old_values = {canonical(r['event']['value']) for r in a}
        old_pairs = {canonical([writer(r['event']), r['event']['value']]) for r in a}
        changed = []
        if comparable:
            for item in b:
                event = item['event']
                nw = canonical(writer(event)) not in old_writers
                nv = canonical(event['value']) not in old_values
                np = canonical([writer(event), event['value']]) not in old_pairs
                if np:
                    changed.append(dict(**item, new_writer=nw, new_value=nv, new_pair=np))
        comparisons.append(dict(identity=json.loads(key), comparable=comparable,
            control=control, generated=generated, changed_generated=changed,
            new_writer=any(r['new_writer'] for r in changed),
            new_value=any(r['new_value'] for r in changed), new_pair=bool(changed)))
    return dict(case=group['case'], group=group['group'], read_counts=dict(reads),
        role_read_counts={key: dict(value) for key, value in roles.items()},
        field_read_counts={key: dict(value) for key, value in fields.items()},
        comparisons=comparisons, unknown=unknown, evidence_sha256=evidence,
        correctness_evaluated=False)


def audit(execution_root, output):
    seal = read(execution_root / 'seal.json')
    for relative, expected in seal['files_sha256'].items():
        if digest(execution_root / relative) != expected:
            raise ValueError('Frozen execution artifact changed: ' + relative)
    execution = read(execution_root / 'summary.json')
    groups = [compare_group(group) for group in execution]
    summaries = []
    for case in sorted({group['case'] for group in groups}):
        selected = [group for group in groups if group['case'] == case]
        prior = [group for group in execution if group['case'] == case]
        counters = Counter()
        for group in selected:
            counters.update(group['read_counts'])
        comparisons = [c for group in selected for c in group['comparisons']]
        changed = [r for c in comparisons for r in c['changed_generated']]
        fields = defaultdict(Counter)
        for group in selected:
            for field, value in group['field_read_counts'].items():
                fields[field].update(value)
        phase_counts = defaultdict(Counter)
        for group in prior:
            for phase in group['phases']:
                phase_counts[phase['role']].update(phase['overlay_counts'])
        new_writer_identities = {canonical(c['identity']) for c in comparisons if c['new_writer']}
        new_value_identities = {canonical(c['identity']) for c in comparisons if c['new_value']}
        summaries.append(dict(case=case, groups=len(selected),
            phases=sum(len(g['phases']) for g in prior),
            all_test_outcomes_unchanged=all(p['outcomes_unchanged'] for g in prior for p in g['phases']),
            all_phase_counts_unchanged=all(p['baseline_counts'] == p['overlay_counts'] for g in prior for p in g['phases']),
            phase_outcome_counts={k: dict(v) for k, v in phase_counts.items()},
            reads=dict(counters), field_reads={k: dict(v) for k, v in fields.items()},
            shared_group_q=len(comparisons), comparable_group_q=sum(c['comparable'] for c in comparisons),
            group_q_with_new_writer=sum(c['new_writer'] for c in comparisons),
            group_q_with_new_value=sum(c['new_value'] for c in comparisons),
            group_q_with_new_pair=sum(c['new_pair'] for c in comparisons),
            distinct_source_q_with_new_writer=len(new_writer_identities),
            distinct_source_q_with_new_value=len(new_value_identities),
            generated_events_with_new_writer=sum(r['new_writer'] for r in changed),
            generated_events_with_new_value=sum(r['new_value'] for r in changed),
            changed_generated_events_with_edited_assertion=sum(r['event']['source_assertion_edited'] for r in changed),
            unknown_reasons=dict(Counter(r['event']['reason'] for group in selected for r in group['unknown'])),
            correctness_evaluated=False))
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'comparisons.json', groups)
    write(output / 'summary.json', summaries)
    write(output / 'provenance.json', dict(
        execution_root=str(execution_root.resolve()), execution_seal_sha256=digest(execution_root / 'seal.json'),
        verified_execution_files=len(seal['files_sha256']), script_sha256=digest(Path(__file__)),
        comparison='All groups; control and generated observations share exact source q, source construction, source SHA, resolved class and field. Source profiles contribute read totals but not control comparisons.',
        selection='No target, verdict, failure status, or outcome filtering.',
        interpretation='A new writer/value pair is an observed state distinction, not evidence of correct expectations or a bug. Historical source paths remain distinct. Counts include repeated groups and control observations.',
        external_write_coverage_complete=False, correctness_evaluated=False))
    write(output / 'seal.json', dict(files_sha256={str(p.relative_to(output)): digest(p)
        for p in sorted(output.rglob('*')) if p.is_file()}))
    return summaries


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--execution', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(audit(args.execution, args.output), sort_keys=True))
