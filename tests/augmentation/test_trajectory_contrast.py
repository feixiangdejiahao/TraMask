import json
import pytest

from augmentation.trajectory_contrast import compute_contrasts, decode_observation, finite_eval, query_fact, test_facts as extract_facts, trajectory_index, feedback_excerpt


def fixture(code,language="typescript"):
    return extract_facts([{"id":"t","path":"subject.ts","line":10,"code":code}],language)


def test_literal_bindings_keep_omitted_and_explicit_undefined_distinct():
    facts=fixture("run({mode:undefined}); run({}); run({mode:'put'});")
    index={f["id"]:f for f in facts}
    q=lambda f,mode:{"call_id":f["id"],"argument":0,"path":["mode"],"get":mode}
    assert query_fact(q(facts[0],"present"),index)[0] is True
    assert query_fact(q(facts[0],"value"),index)[0]=="UNDEFINED"
    assert query_fact(q(facts[1],"present"),index)[0] is False
    assert query_fact(q(facts[1],"value"),index)[0]=="ABSENT"
    assert query_fact(q(facts[2],"value"),index)[0]=="put"


def test_spread_does_not_prove_property_absence():
    facts=fixture("run({...options});")
    with pytest.raises(ValueError,match="nonliteral"):
        query_fact({"call_id":facts[0]["id"],"argument":0,"path":["mode"],"get":"present"},{f["id"]:f for f in facts})


def test_identifier_not_misrepresented_as_literal_value():
    facts=fixture("const opts = {mode:'put'}; run(opts);")
    with pytest.raises(ValueError,match="path_not_grounded"):
        query_fact({"call_id":facts[0]["id"],"argument":0,"path":["mode"],"get":"value"},{f["id"]:f for f in facts})


def test_no_arbitrary_code_evaluation():
    with pytest.raises(ValueError,match="unsupported_expression"):
        finite_eval("__import__('os').system('false')",{})
    assert finite_eval("x if present else 'default'",{"x":"UNDEFINED","present":True})=="UNDEFINED"
    assert finite_eval("mode or 'put'",{"mode":None})=="put"


def test_model_values_are_not_counted_as_extracted_test_evidence():
    plan={"models":[{"id":"m","domains":{"present":[False,True],"undefined":[False,True]},
                     "current_expr":"undefined","required_expr":"not present","feasible_expr":"present or undefined",
                     "validation_rows":[{"id":"v","bindings":{},"suggested_values":{"present":False,"undefined":True}}]}]}
    result=compute_contrasts(plan,[])[0]
    assert result["complete_literal_bound_rows"]==0
    assert result["difference_count"]==1
    assert result["witnesses"][0]["factors"]=={"present":True,"undefined":True}


def test_grounded_row_guides_counterexample_without_cross_test_mixing():
    facts=fixture("run({mode:'put'}); run({mode:'update'});")
    bind=lambda f:{"call_id":f["id"],"argument":0,"path":["mode"],"get":"value"}
    plan={"models":[{"id":"m","domains":{"mode":["ABSENT","put","update"]},
                     "current_expr":"mode == 'put'","required_expr":"mode in ['ABSENT', 'put']",
                     "validation_rows":[{"id":"v","bindings":{"mode":bind(facts[0])}}]}]}
    result=compute_contrasts(plan,facts)[0]
    assert result["complete_literal_bound_rows"]==1
    assert result["checked_rows"][0]["distinguishes_local_expressions"] is False
    assert result["witnesses"][0]["factors"]=={"mode":"ABSENT"}
    plan["models"][0]["domains"]["other"]=["put","update"]
    plan["models"][0]["validation_rows"][0]["bindings"]["other"]=bind(facts[1])
    result=compute_contrasts(plan,facts)[0]
    assert result["complete_literal_bound_rows"]==0
    assert any(x["reason"]=="bindings_mix_distinct_test_statements" for x in result["binding_errors"])


def test_nested_observation_preserves_failure_even_with_zero_exit_code():
    output,codes=decode_observation({"observation":{"results":[{"content":'{"returncode":0,"output_head":"match=false\\\\nexpected=x"}'}]}})
    assert codes==[0]
    assert "match=false\nexpected=x"==output


def test_python_inline_mapping_binding():
    facts=fixture("check({'mode': 'put', 'on': False})", "python")
    value,_=query_fact({"call_id":facts[0]["id"],"argument":0,"path":["on"],"get":"value"},{f["id"]:f for f in facts})
    assert value is False


def test_go_keyed_literals_and_slice_length():
    facts=fixture('func T() { run(Opts{Mode:"put"}); run([]int{1,2}) }', "go")
    index={f["id"]:f for f in facts}
    assert query_fact({"call_id":facts[0]["id"],"argument":0,"path":["Mode"],"get":"value"},index)[0]=="put"
    assert query_fact({"call_id":facts[1]["id"],"argument":0,"get":"length"},index)[0]==2


def test_early_failed_validation_is_preserved_with_nearby_edit(tmp_path):
    def step(i,command,output):
        return {"step_id":i,"tool_calls":[{"arguments":{"command":command}}],
                "observation":{"results":[{"content":json.dumps({"returncode":0,"output":output})}]}}
    trajectory=tmp_path/'trajectory.json'
    trajectory.write_text(json.dumps({"steps":[step(1,'go run /tmp/check.go','match=false'),
        step(2,'cat > subject.go <<EOF\nchanged\nEOF','')]+[step(i,'cat other.go','no issue') for i in range(3,80)]}))
    history,events=trajectory_index({"trajectory":str(trajectory)}, {"changed_paths":["subject.go"],"validation_tests":[]})
    assert len(history["timeline"])==79
    assert any(e["step"]==1 and e["failure_text_in_execution"] for e in history["episodes"])
    assert any(e["step"]==2 and 'edit_near_execution' in e["selection"] for e in history["episodes"])
    assert any(e["step"]==2 and 'edit_adjacent_assertion_feedback' in e["selection"] for e in history["episodes"])


def test_passing_failure_handling_test_name_is_not_failure_feedback():
    assert feedback_excerpt('PASS test.ts\n ✓ rolls back on failure\nTests: 3 passed, 3 total')[1] is False
    assert feedback_excerpt('FAIL test.ts\nReceived: undefined\nTests: 1 failed, 2 passed')[1] is True
