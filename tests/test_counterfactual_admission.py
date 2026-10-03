import json
from relation_search import counterfactual_admission as method


def fixture():
    return method.from_compact_request(dict(id='old',check_ids=['P','Q0'],prompt=json.dumps(
        dict(checks={'P':{},'Q0':dict(requires='guard_false_on_normal_completion',
                                    expression={'text':'before != after'})}))))


def test_passing_condition_inverts_failure_guard():
    payload=json.loads(fixture()['prompt'])
    assert payload['checks']['Q0']['passing_condition']=={'logical_not':{'text':'before != after'}}


def test_counterexample_cannot_coexist_with_acceptance():
    value=dict(counterexamples=[dict(check='Q0',test_requires='Same content',
               correct_behavior='Different databases have different content',basis='Different resource paths')],
               passes={'P':True,'Q0':True})
    assert method.decide(fixture(),value)['reason']=='counterexample_verdict_conflict'
    value['passes']['Q0']=False
    assert method.decide(fixture(),value)['status']=='semantic_rejected'


def test_unknown_does_not_become_false_or_true():
    value=dict(counterexamples=[],passes={'P':True,'Q0':None})
    assert method.decide(fixture(),value)['status']=='unknown'
    value['passes']['Q0']=1
    assert method.decide(fixture(),value)['reason']=='invalid_pass_boolean'
