import json
from types import SimpleNamespace

from scripts import replay_codec_guarded_semantics as runner


def prepare(tmp_path):
    source = tmp_path/'source'
    items = []
    for case, after in [('plain', 'other'), ('encoded', '__import__("shlex").quote(value)')]:
        payload = dict(language='python', original_test='def test_case(): pass',
                       modified_test='def test_case(): pass', source_analysis='',
                       input_edits=[dict(before='value', after=after)])
        request = source/case/'request.json'
        runner.write(request, dict(prompt=json.dumps(payload)))
        items.append(dict(case=case, candidate_id=case+'1', first_request=runner.frozen(request)))
    runner.write(source/'prepared.json', dict(version=runner.baseline.VERSION,
        cases=['plain', 'encoded', 'empty'], items=items))
    runner.write(source/'seal.json', runner.frozen(source/'prepared.json'))
    root = tmp_path/'guarded'
    assert runner.prepare(SimpleNamespace(source=source, output=root))['trials'] == 3
    return root


def summary():
    return dict(denominator=3, compatible_cached_reviews=2, compatible_cached_review_tokens=15,
                first_stage_calls=3, first_stage_tokens=20, entire_second_gate_experiment_cost=dict(calls=2, tokens=15),
                decisions=[dict(case=case, candidate_id=case+'1', decision=dict(alarm_eligible=True))
                           for case in ['plain', 'encoded']])


def test_same_guard_withholds_codec_assumption_without_replacing_a_candidate(tmp_path):
    root = prepare(tmp_path)
    runner.write(root/'semantic/summary.json', summary())
    result = runner.run(SimpleNamespace(input=root))
    assert result['denominator'] == 3 and result['alerts'] == 1
    output = runner.read(root/'summary.json')
    assert [row['case'] for row in output['alerts']] == ['plain']
    withheld = next(row for row in output['decisions'] if row['case'] == 'encoded')
    assert withheld['prior_decision']['alarm_eligible']
    assert withheld['decision']['withheld_not_invalid']
    assert output['first_stage_tokens'] == 20


def test_chain_copy_restores_exact_inner_protocol_in_new_execution_root(tmp_path, monkeypatch):
    original = prepare(tmp_path)
    copied = tmp_path/'copy'
    runner.write(copied/'prepared.json', runner.read(original/'prepared.json'))
    runner.write(copied/'seal.json', runner.frozen(copied/'prepared.json'))
    called = []
    def replay(args):
        called.append(args.input)
        assert runner.read(args.input/'prepared.json') == runner.read(original/'semantic/prepared.json')
        runner.verify(runner.read(args.input/'seal.json'))
        runner.write(args.input/'summary.json', summary())
    monkeypatch.setattr(runner.baseline, 'run', replay)
    result = runner.run(SimpleNamespace(input=copied))
    assert result['alerts'] == 1
    assert called == [copied/'semantic']
