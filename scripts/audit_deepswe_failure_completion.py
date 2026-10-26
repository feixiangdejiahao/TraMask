"""Verify the scope and artifacts of the completed manual study; never infer semantics."""
from collections import Counter
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / 'research/deepswe_failure_manual_20261006'


def read(path):
    return json.loads(path.read_text())


def receipt(path):
    return {'path': str(path.relative_to(ROOT)),
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class ReportInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.trials = []
        self.local_links = []

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'details' and 'trial' in attrs.get('class', '').split():
            self.trials.append(attrs['id'].removeprefix('trial-'))
        if tag == 'a' and attrs.get('href', '').startswith('../'):
            self.local_links.append(attrs['href'])


def run():
    cohort = read(STUDY / 'cohort_audit.json')
    expected = set(cohort['trial_names'])
    assert len(expected) == 211
    acquisition = read(ROOT / 'results/deepswe_failure_manual_20261006/acquisition_summary.json')
    assert acquisition['ready'] == acquisition['expected'] == 211
    primary_checkpoint = read(STUDY / 'evidence_checkpoint.json')
    cross_checkpoint = read(STUDY / 'cross_review/evidence_checkpoint.json')
    assert primary_checkpoint['literal_evidence_checks_passed'] == 211
    assert cross_checkpoint['current_accepted_receipts'] == 211
    assert not cross_checkpoint['pending_trials'] and not cross_checkpoint['issues']
    assert {row['trial'] for row in primary_checkpoint['checked_reports']} == expected
    assert {row['trial'] for row in cross_checkpoint['accepted_reports']} == expected
    synthesis_path = STUDY / 'method_synthesis.json'
    synthesis = read(synthesis_path)
    for field in ['summary_paragraphs', 'design_basis', 'proposed_abstraction',
                  'novelty_assessment', 'pilot_design', 'limits']:
        assert synthesis.get(field), f'missing synthesis: {field}'
    examples = []
    for basis in synthesis['design_basis']:
        assert basis.get('title') and basis.get('explanation') and basis.get('examples')
        for example in basis['examples']:
            trial = example['trial']
            assert trial in expected
            trajectory = read(ROOT / 'results/deepswe_failure_manual_20261006/trials' / trial / 'trajectory.json')
            ids = {step['step_id'] for step in trajectory['steps']}
            grouped_steps = example.get('steps', [])
            example_steps = [step for group in grouped_steps.values() for step in group] if isinstance(grouped_steps, dict) else grouped_steps
            assert set(example_steps) <= ids
            for field in ['original_checks', 'missing_relation', 'program_signal',
                          'trajectory_signal', 'qualification']:
                assert example.get(field), f'incomplete design example: {trial}: {field}'
            examples.append({'basis': basis['title'], 'trial': trial, 'steps': example.get('steps', [])})
    report_path = ROOT / 'docs/20261022_deepswe_failure_analysis_n211.html'
    report_text = report_path.read_text()
    parser = ReportInventory()
    parser.feed(report_text)
    assert len(parser.trials) == len(set(parser.trials)) == 211
    assert set(parser.trials) == expected
    assert 'DeepSWE 全部失败记录：验证缺口与方法设计依据' in report_text
    assert '全量审查对方法设计的启示' in report_text
    # This audit file is written below. All other relative file targets must already exist.
    for link in parser.local_links:
        target = (report_path.parent / link.split('#', 1)[0]).resolve()
        assert target == STUDY / 'completion_audit.json' or target.exists(), f'missing report link: {link}'
    rows, tally, second_reviewers = [], Counter(), Counter()
    questions = ['validation_inventory', 'combination_gaps', 'selection_problems',
                 'program_relations', 'trajectory_sequence', 'direct_evidence',
                 'causal_hypotheses', 'counter_evidence', 'version_audit',
                 'method_design_implications', 'limits']
    for trial in sorted(expected):
        primary_path = STUDY / 'trials' / (trial + '.json')
        cross_path = STUDY / 'cross_review/trials' / (trial + '.json')
        primary, cross = read(primary_path), read(cross_path)
        assert all(field in primary for field in questions)
        assert cross['status'] == 'accepted' and cross['reviewer'] != cross['primary_reviewer']
        primary_receipt = receipt(primary_path)
        assert cross['primary_report_receipt'] == primary_receipt
        assert cross['inspection_scope'] and cross['claim_checks']
        for source in primary['source_receipts'].values():
            assert receipt(ROOT / source['path'])['sha256'] == source['sha256']
        tally[primary['verdict']] += 1
        second_reviewers[cross['reviewer']] += 1
        rows.append({'trial': trial, 'verdict': primary['verdict'],
                     'primary_report_receipt': primary_receipt,
                     'second_review_receipt': receipt(cross_path),
                     'second_reviewer': cross['reviewer'],
                     'source_receipts': primary['source_receipts']})
    audit = {
        'updated_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'all_211_manual_reviews_second_reviews_and_synthesis_complete',
        'expected_trials': 211, 'primary_reports': len(rows), 'accepted_second_reviews': len(rows),
        'tasks': cohort['counts']['failure_tasks'], 'repositories': cohort['counts']['failure_repositories'],
        'descriptive_verdict_counts': dict(tally), 'second_reviewer_counts': dict(second_reviewers),
        'scope_receipt': receipt(STUDY / 'cohort_audit.json'),
        'primary_checkpoint_receipt': receipt(STUDY / 'evidence_checkpoint.json'),
        'second_checkpoint_receipt': receipt(STUDY / 'cross_review/evidence_checkpoint.json'),
        'synthesis_receipt': receipt(synthesis_path), 'report_receipt': receipt(report_path),
        'design_examples': examples, 'review_records': rows,
        'work_performed': [
            'The reviewing agents inspected the original public operation sequences, relevant expanded windows, requirements, original tests and final patches.',
            'Each primary report answers the three requested questions and records scope, contrary evidence, code version and causal limits.',
            'A different AI reviewing agent checked original evidence for each of the 211 substantive reports and recorded claim-specific decisions.',
            'The report explains the dataset, judgment procedure, descriptive results, method basis, contribution hypotheses and proposed pilots.'
        ],
        'limits': [
            'This script verifies membership, current receipts, required artifacts and report coverage. It cannot establish semantic correctness.',
            'Semantic decisions are the manually written, nonblind AI reviews; they are not independent human ground truth.',
            'A verification gap is not a confirmed patch defect or the cause of the official failure.',
            'The failed-only cohort and repeated tasks do not measure a detector, estimate prevalence or establish algorithm novelty.'
        ],
        'new_provider_calls': 0, 'new_subject_executions': 0,
        'hidden_tests_or_reference_implementation_used': False,
    }
    (STUDY / 'completion_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: audit[key] for key in ['status', 'expected_trials', 'primary_reports',
                                                'accepted_second_reviews', 'tasks', 'repositories',
                                                'descriptive_verdict_counts']}, ensure_ascii=False))


if __name__ == '__main__':
    run()
