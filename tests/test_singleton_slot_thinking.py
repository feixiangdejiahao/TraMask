import pytest
from scripts.diagnose_singleton_slot_thinking import change_thinking
from scripts.run_singleton_expected_slots_diagnostic import wire_payload


def test_thinking_is_the_only_wire_change_and_request_is_not_mutated():
    original=dict(id='fixed',system='fixed system',prompt='fixed full program',thinking='disabled',
                  source_sha256={'test.py':'identity'})
    changed=change_thinking(original)
    assert original['thinking']=='disabled'
    assert {k:v for k,v in changed.items() if k!='thinking'}=={k:v for k,v in original.items() if k!='thinking'}
    before,after=wire_payload(original),wire_payload(changed)
    assert after['thinking']=={'type':'enabled'}
    assert {k:v for k,v in after.items() if k!='thinking'}=={k:v for k,v in before.items() if k!='thinking'}
    assert after['max_tokens']==16384 and 'reasoning_effort' not in after


@pytest.mark.parametrize('extra',[dict(thinking='enabled'),dict(reasoning_effort='low')])
def test_rejects_a_different_source_condition(extra):
    with pytest.raises(ValueError):
        change_thinking(dict(system='x',prompt='y',thinking='disabled')|extra)
