"""Immutable receipt audit; semantic case judgments are written manually."""
from pathlib import Path
import hashlib
import importlib.util
import json
from datetime import datetime, timezone

RUN = Path(__file__).resolve().parent.parent
ROOT = RUN.parents[2]
spec = importlib.util.spec_from_file_location('review_audit', ROOT / 'scripts/audit_fragment_reviews.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def read(p):
    return json.loads(p.read_text())


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


reviews = []
for who in ['A', 'B']:
    for path in sorted((RUN / f'observation/reviewer_{who}').glob('S[0-9][0-9][0-9].json')):
        history = read(RUN / f'public_inputs/{path.stem}/history.json')
        reviews.append({'reviewer': who, **module.audit_review(path, history)})

rows, errors = [], []
for path in sorted((RUN / 'observation/adjudicated').glob('S[0-9][0-9][0-9].json')):
    d = read(path)
    cid = path.stem
    e = []
    for key in ['case_id', 'trial', 'status', 'reviews', 'target_operation',
                'required_factor_inventory', 'missing_factors', 'oracle_availability',
                'fragment_compatibility', 'minimal_assembly', 'counts']:
        if key not in d:
            e.append('missing_field:' + key)
    if d.get('case_id') != cid:
        e.append('case_identity')
    frozen = {}
    for who, r in d['reviews'].items():
        source = RUN / r['path']
        if not source.is_file() or sha(source) != r['sha256']:
            e.append('frozen_review_hash:' + who)
        else:
            frozen[who] = read(source)
            if frozen[who]['trial'] != d['trial'] or frozen[who]['case_id'] != cid:
                e.append('frozen_review_identity:' + who)
    # Older canonical records legitimately keep the base in a frozen review.
    if not d.get('agent_base_units') and not any(x.get('agent_base_units') for x in frozen.values()):
        e.append('base_unit_unavailable')
    labels = [f.get('provenance_class', f.get('history_provenance')) for f in d['missing_factors']]
    for key, value in {'missing_factor_count': len(labels),
                       'missing_exact': labels.count('Exact Executed Fragment'),
                       'missing_related': labels.count('Related Executed Components'),
                       'missing_absent': labels.count('Absent'),
                       'missing_unresolved': labels.count(None)}.items():
        if d['counts'].get(key) != value:
            e.append('count:' + key)
    history = {a['id']: a for a in read(RUN / f'public_inputs/{cid}/history.json')['actions']}
    checks = d.get('root_source_checks', {})
    # Older records wrap checks in a list; retain checks of embedded receipts.
    check_items = checks if isinstance(checks, list) else [checks]
    receipts = [rec for item in check_items if isinstance(item, dict)
                for rec in item.get('action_receipts', [])]
    for rec in receipts:
        if any(history.get(rec['id'], {}).get(k) != v for k, v in rec.items()):
            e.append('root_action_receipt:' + rec['id'])
    errors.extend({'case_id': cid, 'error': item} for item in e)
    rows.append({'case_id': cid, 'path': str(path), 'sha256': sha(path), 'errors': e})

result = {'schema_version': 'fragment-progress-integrity.v1',
          'observed_at': datetime.now(timezone.utc).isoformat(),
          'reviews_checked': len(reviews), 'review_errors': sum(len(x['errors']) for x in reviews),
          'review_warnings': sum(len(x['warnings']) for x in reviews),
          'adjudications_checked': len(rows), 'adjudication_errors': errors,
          'reviews': reviews, 'adjudications': rows,
          'scope': 'Source receipt/identity/count audit only; no automatic semantic endorsement or candidate execution.'}
attempt = 5
while (RUN / f'observation/adjudication_integrity_attempt_{attempt:03d}.json').exists():
    attempt += 1
out = RUN / f'observation/adjudication_integrity_attempt_{attempt:03d}.json'
with out.open('x') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write('\n')
print(json.dumps({k: v for k, v in result.items() if k not in ['reviews', 'adjudications']}))
print(out)
