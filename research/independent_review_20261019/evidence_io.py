"""Access ledger for this independent review. No original data are modified."""
from pathlib import Path
import datetime
import hashlib
import json

ROOT = Path('/home/jhx/combination_coverage')
OUT = ROOT / 'research/independent_review_20261019'
LEDGER = OUT / 'evidence_access.json'

def record(path, scope, stage=None):
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    frozen = (OUT / 'independent_initial_findings.txt').exists()
    data = p.read_bytes()
    row = {
        'path': str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p),
        'access_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'before_initial_findings_frozen': not frozen if stage is None else stage == 'initial',
        'scope': scope,
        'sha256': hashlib.sha256(data).hexdigest(),
        'bytes': len(data),
    }
    obj = json.loads(LEDGER.read_text()) if LEDGER.exists() else {
        'review': 'independent software engineering research review 2026-10-19',
        'access_boundary': 'No prior synthesis, case explanations, design proposals, debate, or unfiltered protocols were read.',
        'entries': [],
        'web_sources': [],
    }
    obj['entries'].append(row)
    LEDGER.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    return data.decode('utf-8')

def read_json(path, scope, stage=None):
    return json.loads(record(path, scope, stage))
