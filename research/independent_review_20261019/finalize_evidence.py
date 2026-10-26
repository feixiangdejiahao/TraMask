from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json

OUT = Path(__file__).resolve().parent
ROOT = OUT.parent.parent
ledger = json.loads((OUT / 'evidence_access.json').read_text())
now = datetime.now(timezone.utc).isoformat()

for entry in ledger['entries']:
    if entry['scope'] == 'Full submitted patch T28':
        entry['scope'] = 'Requested full submitted patch T28; tool display truncated. Selected query.ts/tests and createPersister ranges inspected separately; no full-patch semantic-review claim.'
    if entry['path'] == 'scripts/run_validation_evolution_pilot_v3.py' and entry['before_initial_findings_frozen']:
        entry['scope'] += '; combined display had truncation, so not a claim of inspecting every line of this file'

retrospective = [
    'scripts/run_observation_feedback_pilot.py',
    'src/augmentation/observation_feedback.py',
    'src/augmentation/program.py',
    'generic_composition/runner.py',
]
existing = {x['path'] for x in ledger['entries']}
for rel in retrospective:
    q = ROOT / rel
    if rel not in existing and q.exists():
        ledger['entries'].append({
            'path': rel,
            'access_utc': None,
            'recorded_utc': now,
            'before_initial_findings_frozen': True,
            'scope': 'Retrospective record of pre-freeze rg path/keyword-only lookup. No full source review. Precise original lookup time not retained.',
            'sha256_at_final_audit': hashlib.sha256(q.read_bytes()).hexdigest(),
            'bytes': q.stat().st_size,
        })

raw = json.loads((OUT / 'raw_counterexamples_access.json').read_text())
lit = json.loads((OUT / 'independent_literature_access.json').read_text())
ledger['subagents'] = [
    {
        'task': '/root/independent_research_review_20261019/raw_counterexamples',
        'delegation_authorization': 'Explicit subsequent user authorization allowing new Codex to use subagents; overrides brief no-subthread note.',
        'assignment': 'Independently inspect original T02/T15/T23/T29 evidence, seek counterexamples and alternative explanations, no scores/gold/augmentation outputs.',
        'history_fork': 'none',
        'own_written_report_first_read_before_initial_freeze': False,
        'read_project_historical_evaluations': False,
        'source_access_times_vs_main_initial_freeze': 'Not individually timestamped by child; may span the main freeze. All child conclusions formed without historical evaluations. Main import of complete report occurred after freeze.',
        'file_log': 'raw_counterexamples_access.json',
        'notes': 'raw_counterexamples_notes.txt',
        'files': raw['files'],
        'independent_opinion': 'Strong original tests and legitimate oracle/test edits refute a universal single-feature or test-weakening account; concrete path/identity/timing insufficiency matters; static candidates are not confirmed defects.',
    },
    {
        'task': '/root/independent_research_review_20261019/independent_literature',
        'assignment': 'Select and verify primary papers independently, including adversarial novelty checks, without project notes or a parent-selected paper list.',
        'history_fork': 'none',
        'preliminary_message_before_initial_freeze': 'Existence and reference-implementation dependence of two 2026 benchmark-hardening papers; disclosed in frozen initial findings.',
        'own_written_report_first_read_before_initial_freeze': False,
        'read_project_historical_evaluations': False,
        'source_access_times_vs_main_initial_freeze': 'Individual web times not retained by child; independent search spanned main freeze. Complete notes imported afterward.',
        'file_log': 'independent_literature_access.json',
        'notes': 'independent_literature_notes.txt',
        'project_files': lit['project_files_read'],
        'skills_read': lit['skill_files_read'],
        'primary_sources': lit['primary_sources'],
        'independent_opinion': 'PROBE and TestJack are close precedents; no-gold inputs and PA/LLM combination alone are not novelty. Need same-budget evidence that a particular diagnostic changes decisions and effective defect discovery.',
    },
]

ledger['web_sources'] = [
    {
        'reviewer': 'independent_literature subagent',
        'source_id': x['id'],
        'urls': x['urls'],
        'sections_read': x['sections_read'],
        'verification_notes': x['notes'],
        'before_main_initial_freeze': 'See subagent preliminary-exposure disclosure; complete report imported after freeze.',
    }
    for x in lit['primary_sources']
] + [
    {
        'reviewer': 'main independent reviewer',
        'urls': ['https://arxiv.org/abs/1811.08330', 'https://github.com/STAMP-project/dspot', 'https://github.com/STAMP-project/dspot-experiments'],
        'scope': 'Primary search abstracts/snippets only; DSpot not used for detailed quantitative or mechanistic claims in final report.',
        'before_initial_findings_frozen': False,
    },
    {
        'reviewer': 'main independent reviewer',
        'urls': ['https://www.cse.ust.hk/faculty/scc/publ/CS98-01-metamorphictesting.pdf', 'https://arxiv.org/abs/2002.12543'],
        'scope': 'Author-hosted original technical report metadata and primary search abstract. PDF text extraction garbled; attempted page-2 screenshots did not yield a model-viewable image through wrapper. No claim of reading the garbled full text.',
        'supported_claim': 'Classical metamorphic testing derives follow-up tests from successful tests and uses input/output relations; this basic mechanism is not new.',
        'failed_access': ['https://arxiv.org/html/2002.12543 returned 404'],
        'before_initial_findings_frozen': False,
    },
    {
        'reviewer': 'main independent reviewer',
        'urls': ['https://arxiv.org/abs/2310.19204', 'https://arxiv.org/html/2310.19204v2'],
        'scope': 'Primary metadata and HTML sections 1–4; most body displayed. Not an experiment replication.',
        'supported_claim': 'LLM-generated metamorphic relations have prior work; expert review distinguishes valid, incorrect, and unjustifiable candidates. A relation-generation prompt alone is not novel or an oracle guarantee.',
        'before_initial_findings_frozen': False,
    },
    {
        'reviewer': 'main independent reviewer',
        'urls': ['https://superhangdu.com/publications/icse-24/conference-paper.pdf', 'https://ieeexplore.ieee.org/document/10548566/', 'https://github.com/spideruci/RIPR-framework', 'https://zenodo.org/records/10505175'],
        'scope': 'Author PDF introduction/background/selected methodology excerpts approximately lines 62–403, plus selected conclusion/limitations snippets via find; publisher/artifact search abstracts. Did not audit artifact code or reproduce experiments.',
        'supported_claim': 'Reachability, infection, propagation and revelation are distinct; propagation can escape assertion checks. This is established background, not a new theory of this report.',
        'before_initial_findings_frozen': False,
    },
]

ledger['review_limits'] = [
    'Thirty original issues read; full repository audit and full trajectory review not performed.',
    'Hashing all 211 instruction files establishes duplicate groups only; semantic reading limited as logged.',
    'All historical counts remain historical AI judgments unless separately verified. Main directly audited one T17 candidate/gold execution pair, selected other comparison files and gold source ranges.',
    'Actual implementation prompts and protocol-generation strings were visible before initial freeze. No old synthesis/review explanations/design documents were read.',
    'Child reading is independently logged; exact per-file child timestamps relative to main freeze are unavailable and are not fabricated.',
    'No new provider calls or test executions; no changes to original data or algorithms. Shell programs only read/parse evidence and write review artifacts.',
]
ledger['post_draft_factual_corrections'] = [
    {
        'case': 'T08',
        'source_of_pointer': 'Parent provided only original trajectory path, steps[35]/steps[36], and the test name; no research interpretation or design suggestion was adopted.',
        'independent_verification': 'Main reviewer read command context and raw observations. steps[35] has step_id 36 and defines test_missing_closing_delimiter expecting one part with body text; observations in steps[35] and steps[36] both contain PASS test_missing_closing_delimiter.',
        'report_correction': 'Final patch omission cannot imply that original trajectory never tested the input. Correct EOF framing oracle remains unconfirmed here; T08 is not counted as a missed-input or confirmed-defect example.',
        'initial_notes_modified': False,
        'source_access_logged': True,
    }
]
ledger['final_audit'] = {
    'utc': now,
    'initial_findings_sha256_unchanged': hashlib.sha256((OUT / 'independent_initial_findings.txt').read_bytes()).hexdigest() == ledger['initial_findings_freeze']['sha256'],
    'historical_counts_recomputed_file': 'independent_numeric_audit.json',
    'final_report_write_order': 'TXT then HTML',
    'new_provider_calls': 0,
    'new_test_executions': 0,
    'external_resource_dependencies_in_html': 0,
    'outputs': {},
}
for name in ['independent_initial_findings.txt', 'independent_report.txt', 'independent_report.html', 'independent_numeric_audit.json', 'independent_sampling.json', 'raw_counterexamples_notes.txt', 'raw_counterexamples_access.json', 'independent_literature_notes.txt', 'independent_literature_access.json']:
    q = OUT / name
    ledger['final_audit']['outputs'][name] = {'bytes': q.stat().st_size, 'sha256': hashlib.sha256(q.read_bytes()).hexdigest()}
(OUT / 'evidence_access.json').write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'file_access_entries': len(ledger['entries']), 'web_source_groups': len(ledger['web_sources']), 'subagents': len(ledger['subagents']), 'initial_unchanged': ledger['final_audit']['initial_findings_sha256_unchanged']}, ensure_ascii=False))
