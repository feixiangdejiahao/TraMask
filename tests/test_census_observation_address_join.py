"""Independent AST metric distinguishes actions from comments and operators."""
import pytest
import hashlib
import json
from scripts.census_observation_address_join import ast_hash, verify_receipt


@pytest.mark.parametrize('language,path,original,formatting,changed', [
    ('python','t.py','def test():\n    obj.put("a",1)\n','def test():\n    # note\n    obj.put( "a", 1 )\n','def test():\n    obj.put("b",1)\n'),
    ('go','t.go','package p\nfunc T(){ x=1+2 }','package p\n// note\nfunc T() { x = 1 + 2 }','package p\nfunc T(){ x=1-2 }'),
    ('typescript','t.ts','function t(){ x.set("a",1); }','function t() { /*note*/ x.set("a", 1); }','function t(){ x.set("b",1); }'),
])
def test_ast_novelty_ignores_formatting_but_preserves_key_and_operator_changes(language,path,original,formatting,changed):
    digest = ast_hash(original.encode(),language,path)
    assert ast_hash(formatting.encode(),language,path) == digest
    assert ast_hash(changed.encode(),language,path) != digest


def receipt():
    budget = dict(max_candidates=16, max_attempts=128, max_actions_per_group=32)
    planned = [dict(q='first'), dict(q='second')]
    digest = lambda rows: hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return budget, dict(mode='address', budget=budget, provider_calls=0, native_executions=0,
        scheduled_pairs=planned, attempted_pairs=planned[:1], scheduled_pair_count=2, attempts=1,
        candidates=[dict(id='candidate')], pair_schedule_sha256=digest(planned),
        attempted_pair_schedule_sha256=digest(planned[:1]))


def test_forged_schedule_prefix_cannot_pass_with_correct_count():
    budget, result = receipt()
    verify_receipt(result, 'address', budget)
    result['attempted_pairs'] = result['scheduled_pairs'][1:]
    with pytest.raises(ValueError, match='prefix'):
        verify_receipt(result, 'address', budget)


def test_schedule_hash_is_recomputed_independently():
    budget, result = receipt()
    result['pair_schedule_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='hash'):
        verify_receipt(result, 'address', budget)
