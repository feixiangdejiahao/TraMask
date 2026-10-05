"""Synthetic source-only fixtures. No development-case labels or target execution."""
from copy import deepcopy
import hashlib
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from research_tools.trajectory_gap_pilot_extract import extract, events, RULES, read_receipt


def fixture(files, language='python'):
    data=extract_frontend([Source(path,code,language) for path,code in files.items()])
    return to_emitter_corpus(data),data


def trajectory(*commands):
    return {'steps':[{'step_id':i+1,'source':'agent','message':'',
        'tool_calls':[{'function_name':'run','arguments':{'command':cmd}}],
        'observation':{'results':[{'content':json.dumps({'returncode':0,'output':'historical output'})}]}}
        for i,cmd in enumerate(commands)]}


def gaps(result,rule):
    return [g for g in result['gaps'] if g['rule']==RULES[rule]]


def test_returned_value_without_assertion_link_and_exact_utf8_evidence():
    corpus,frontend=fixture({'lib.py':'def scale(x):\n    return x * 2\n',
        'test_demo.py':'from lib import scale\ndef test_demo():\n    title = "界🙂"\n    scale(2)\n    value = scale(3)\n    assert value == 6\n'})
    result=extract(corpus,frontend,{'steps':[]})
    unobserved=gaps(result,1)
    assert len(unobserved)==1
    assert unobserved[0]['evidence']['call']['arguments'][0]['text']=='2'
    assert unobserved[0]['evidence']['direct_discard']
    test=result['tests'][unobserved[0]['test_ids'][0]]
    assert test['code'].endswith('assert value == 6')
    assert test['sha256']==hashlib.sha256(test['code'].encode()).hexdigest()
    assert '界🙂' in test['code']
    assert unobserved[0]['trajectory_link_status'].startswith('source_only')


def test_historical_validation_then_edit_is_not_a_final_pass():
    corpus,frontend=fixture({'lib.py':'def scale(x):\n    return x * 2\n',
        'test_demo.py':'from lib import scale\ndef test_demo():\n    assert scale(3) == 6\n'})
    tr=trajectory("cat > /tmp/test_probe.py <<'PY'\nfrom lib import scale\ndef test_probe():\n    assert scale(2) == 4\nPY",
        'pytest /tmp/test_probe.py',"sed -i 's/2/3/' lib.py")
    result=extract(corpus,frontend,tr)
    hit=gaps(result,0)
    assert len(hit)==1
    assert hit[0]['step_ids']==['1','2','3']
    assert result['steps']['2']==tr['steps'][1]
    assert hit[0]['strength']=='lexical_weak'
    assert hit[0]['execution_status']=='no_new_execution'
    assert 'No past pass' in hit[0]['evidence']['limitation']
    tr['steps'].extend(trajectory('pytest /tmp/test_probe.py')['steps'])
    tr['steps'][-1]['step_id']=4
    assert not gaps(extract(corpus,frontend,tr),0)


def test_historical_print_only_and_unknown_file_edit_retained_without_execution():
    corpus,frontend=fixture({'lib.py':'def scale(x):\n    return x * 2\n'})
    tr=trajectory("python - <<'PY'\nfrom lib import scale\nprint(scale(2))\nPY",
        "python - <<'PY'\nfrom pathlib import Path\nPath('lib.py').write_text(Path('lib.py').read_text().replace('2','3'))\nPY")
    result=extract(corpus,frontend,tr)
    hit=[g for g in gaps(result,1) if g['evidence'].get('reason')=='historical_print_only_validation']
    assert hit and hit[0]['step_ids']==['1']
    assert any('print(scale(2))' in t['code'] for t in result['tests'].values())
    assert result['history_recovery']


def test_type_only_nonidentity_callback_and_identity_exclusion():
    corpus,frontend=fixture({'lib.ts':'export function map(fn: (x:number)=>number) { return fn(2); }',
        'lib.test-d.ts':"import {map} from './lib'; test('types', () => { expectTypeOf(map(x => x * 2)).toBeNumber(); });",
        'lib.test.ts':"import {map} from './lib'; test('runtime', () => { expect(map(x => x)).toBe(2); });"},'typescript')
    result=extract(corpus,frontend,{'steps':[]})
    hit=gaps(result,2)
    assert len(hit)==1
    assert hit[0]['evidence']['nonidentity_functions'][0]['span']['text']=='x => x * 2'
    assert hit[0]['evidence']['runtime_nonidentity_coverage']=='not_established'
    assert any(not result['tests'][t]['type_only'] for t in hit[0]['test_ids'])
    corpus2,frontend2=fixture({'lib.ts':'export function map(fn: (x:number)=>number) { return fn(2); }',
        'lib.test-d.ts':"test('types', () => { expectTypeOf(map(x => x)).toBeNumber(); });"},'typescript')
    assert not gaps(extract(corpus2,frontend2,{'steps':[]}),2)


def test_whole_object_guard_records_fields_without_claiming_partial_update_bug():
    corpus,frontend=fixture({'lib.py':'def configure(options):\n    if options is not None:\n        return options.left + options.right\n    return 0\n',
        'test_demo.py':'from lib import configure\ndef test_demo():\n    assert configure(None) == 0\n'})
    result=extract(corpus,frontend,{'steps':[]})
    hit=gaps(result,3)
    assert hit and hit[0]['evidence']['controlled_fields']=={'options':['left','right']}
    assert 'require public contracts' in hit[0]['evidence']['limitation']


def test_literal_sql_count_write_signal_is_explicitly_weak():
    corpus,frontend=fixture({'test_demo.py':'''def test_demo():
    predicate = "SELECT COUNT(*) < 5 FROM records"
    update = "UPDATE records SET label = 'x' WHERE id = 1"
    db.run(update)
    assert db.query(predicate)
'''})
    result=extract(corpus,frontend,{'steps':[]})
    hit=gaps(result,4)
    assert any(g['evidence']['count_preserving_update_hypothesis'] for g in hit)
    assert all(g['strength']=='lexical_weak' for g in hit)
    assert all('Table binding' in g['evidence']['limitation'] for g in hit)


def test_planned_call_mismatch_is_not_absence_proof_and_no_labels_used():
    corpus,frontend=fixture({'lib.py':'def scale(x):\n    return x * 2\n',
        'test_demo.py':'from lib import scale\ndef test_demo():\n    assert scale(3) == 6\n'})
    tr=trajectory('pytest test_demo.py')
    tr['steps'][0]['message']='Next I will check scale(91).'
    result=extract(corpus,frontend,tr)
    assert len(gaps(result,5))==1
    assert 'Not a plan-intent proof' in gaps(result,5)[0]['evidence']['limitation']
    tr2=deepcopy(tr);tr2['final_metrics']={'anything':'changed'};tr2['steps'][0]['observation']={'anything':'failed'}
    second=extract(corpus,frontend,tr2)
    assert [(g['id'],g['rank']) for g in result['gaps']]==[(g['id'],g['rank']) for g in second['gaps']]
    tr['steps'][0]['tool_calls'][0]['arguments']['command']='python -c "scale(91)"'
    assert not gaps(extract(corpus,frontend,tr),5)


def test_event_order_and_json_arguments():
    tr={'steps':[{'step_id':4,'tool_calls':[{'arguments':json.dumps({'command':'pytest test_a.py'})},
        {'arguments':{'cmd':"sed -i 's/a/b/' lib.py"}}]}]}
    ev=events(tr)
    assert [x['sequence'] for x in ev]==[0,1]
    assert ev[0]['is_run'] and ev[1]['is_edit']


def test_source_receipt_mismatch_rejected(tmp_path):
    p=tmp_path/'source.json';p.write_text('{}')
    with pytest.raises(ValueError,match='Source receipt changed'):
        read_receipt({'path':str(p),'sha256':'incorrect'})


@pytest.mark.parametrize('command',['go run /tmp/probe.go','npx tsx /tmp/probe.ts','ts-node ./probe.ts','node ./probe.js'])
def test_common_script_runners_are_execution_commands(command):
    assert events(trajectory(command))[0]['is_run']


def test_member_flag_whole_field_return_is_not_a_defaults_proof():
    corpus,frontend=fixture({'lib.ts':'''export function configure(options) {
    if (options.present) return options.values;
    return fallback;
}''','lib.test.ts':"import {configure} from './lib'; test('values', () => { expect(configure({})).toEqual({}); });"},'typescript')
    result=extract(corpus,frontend,{'steps':[]})
    hits=[g for g in gaps(result,3) if g['evidence']['shape']=='member_condition_whole_field_return']
    assert len(hits)==1
    assert hits[0]['evidence']['returned_fields'][0]['text']=='options.values'
    assert 'not established' in hits[0]['evidence']['limitation']
    assert hits[0]['oracle_status'].startswith('unconfirmed')


def test_historical_outcomes_do_not_change_hypothesis_ids_or_ranks():
    corpus,frontend=fixture({'lib.py':'def scale(x):\n    return x * 2\n'})
    tr=trajectory("cat > /tmp/test_probe.py <<'PY'\nfrom lib import scale\ndef test_probe():\n    assert scale(2) == 4\nPY",
        'pytest /tmp/test_probe.py',"sed -i 's/2/3/' lib.py")
    result=extract(corpus,frontend,tr)
    other=deepcopy(tr)
    for step in other['steps']:
        step['observation']={'results':[{'content':'independently changed output'}]}
    changed=extract(corpus,frontend,other)
    assert gaps(result,0)
    assert [(g['id'],g['rank']) for g in result['gaps']]==[(g['id'],g['rank']) for g in changed['gaps']]
    assert result['steps']!=changed['steps']
