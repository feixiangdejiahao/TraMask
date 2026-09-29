import json
import pytest
from scripts.diagnose_singleton_slot_context import without_context
from scripts.run_singleton_expected_slots_diagnostic import wire_payload


def test_only_source_context_removed_with_exact_other_fields_and_system():
    fields=dict(language='python',issue_contract='Specification\n第二行',modified_test='all state operations\nassert x == 1',
        input_changes=[dict(before='1',after='2')],import_bindings=[],source_context={'declarations':['source']},
        editable_assertions=[dict(id='A0',expected='1')],readonly_assertions=[dict(id='A1',code='assert setup')])
    request=dict(id='old',system='unchanged',prompt=json.dumps(fields,ensure_ascii=False,separators=(',',':')),
                 thinking='enabled',offered={'C0':'fixed'},slots={'A0':'fixed'},source_prepared='fixed')
    changed,removed,difference=without_context(request)
    assert json.loads(request['prompt'])==fields
    assert json.loads(changed['prompt'])=={k:v for k,v in fields.items() if k!='source_context'}
    assert removed==fields['source_context'] and '-  "source_context"' in difference
    assert changed['system']==request['system'] and changed['offered']==request['offered']
    assert changed['slots']==request['slots'] and changed['source_prepared']==request['source_prepared']
    before,after=wire_payload(request),wire_payload(changed)
    assert {k:v for k,v in before.items() if k!='messages'}=={k:v for k,v in after.items() if k!='messages'}
    assert 'reasoning_effort' not in after and after['max_tokens']==16384


def test_noncanonical_prompt_rejected_instead_of_unrelated_whitespace_change():
    with pytest.raises(ValueError,match='serialization'):
        without_context(dict(thinking='enabled',system='x',prompt='{"source_context": {}}'))
