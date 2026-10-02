import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts.diagnose_observation_address_gates import diagnose, read_frozen
from tests.test_observation_address_join import source


def test_source_diagnostic_reports_missing_local_action_bank_without_classification():
    frontend = extract_frontend([Source('test_generic.py', source().replace('assert box.get("a")==1', 'assert True'), 'python')])
    result = diagnose(to_emitter_corpus(frontend), frontend)
    sites = result['read_sites']
    assert sites
    assert all(row['first_excluding_gate'] == 'same_file_scope_constructor_action_bank_empty' for row in sites)
    assert all(row['read_effects'] and row['read_call'] for row in sites)


def test_frozen_input_hash_is_verified_before_decode(tmp_path):
    path = tmp_path/'input.json'
    raw = json.dumps({'sources': {}}).encode()
    path.write_bytes(raw)
    receipt = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
    assert read_frozen(receipt) == {'sources': {}}
    path.write_bytes(raw+b' ')
    with pytest.raises(ValueError, match='changed'):
        read_frozen(receipt)
