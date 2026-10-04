from types import SimpleNamespace

import pytest

from scripts import run_ordered_relation_chain as chain
from scripts.run_contract_repair_search import frozen, write


def prepared_sources(tmp_path, stream_cases=None, semantic_runner=None):
    args = SimpleNamespace(defaults=tmp_path/'doc', stream=tmp_path/'stream',
                           fallback=tmp_path/'semantic', output=tmp_path/'combined')
    cases = ['a', 'b', 'c', 'd']
    for name, root, runner in [('documentation', args.defaults, chain.documentation),
                               ('stream', args.stream, chain.stream),
                               ('semantic', args.fallback, semantic_runner or chain.semantic)]:
        selected = stream_cases if name == 'stream' and stream_cases is not None else cases
        payload = dict(version=runner.VERSION, cases=selected if name == 'semantic' else
                       [dict(case=case) for case in selected])
        write(root/'prepared.json', payload)
        write(root/'seal.json', frozen(root/'prepared.json'))
    args.component = ['documentation='+str(args.defaults), 'stream='+str(args.stream), 'semantic='+str(args.fallback)]
    return args


def test_uniform_precedence_retains_first_relation_even_when_another_claims_an_alert(tmp_path):
    args = prepared_sources(tmp_path)
    # No source output summaries exist during preparation.
    assert chain.prepare(args)['trials'] == 4
    for name, alerts, cost in [('documentation', {'a'}, 2), ('stream', {'a', 'b'}, 4)]:
        write(args.output/name/'summary.json', dict(native_executions=cost, results=[
            dict(case=case, alert={'program': name+case} if case in alerts else None)
            for case in ['a', 'b', 'c', 'd']]))
    write(args.output/'semantic/summary.json', dict(decisions=[
        dict(case=case, decision=dict(alarm_eligible=case in {'a', 'b', 'c'}))
        for case in ['a', 'b', 'c', 'd']], first_stage_calls=64, first_stage_tokens=100,
        entire_second_gate_experiment_cost={'calls': 24, 'tokens': 200},
        compatible_cached_reviews=11, compatible_cached_review_tokens=80))
    result = chain.run(SimpleNamespace(input=args.output))
    assert result == dict(alerts=3, denominator=4, fresh_native_executions=6,
                         replayed_native_executions=0, fresh_provider_calls=0)
    summary = chain.read(args.output/'summary.json')
    assert [(r['case'], r['branch']) for r in summary['decisions']] == [
        ('a', 'documentation'), ('b', 'stream'), ('c', 'semantic'), ('d', 'abstain')]
    assert not summary['independent_audit_complete']
    assert summary['semantic_historical_cost']['first_stage_calls'] == 64


def test_different_component_denominators_are_refused_before_preparation(tmp_path):
    args = prepared_sources(tmp_path, stream_cases=['a', 'b', 'c'])
    with pytest.raises(ValueError, match='same denominator'):
        chain.prepare(args)
    assert not args.output.exists()


def test_duplicate_or_unregistered_components_and_nonfinal_semantic_are_refused(tmp_path):
    args = prepared_sources(tmp_path)
    for components in [['documentation=a', 'documentation=b', 'semantic=c'],
                       ['unknown=a', 'semantic=c'], ['semantic=a', 'documentation=b'], []]:
        args.component = components
        with pytest.raises(ValueError):
            chain.prepare(args)


def test_guarded_semantic_protocol_selects_its_runner_by_exact_version(tmp_path):
    args = prepared_sources(tmp_path, semantic_runner=chain.codec)
    assert chain.prepare(args)['trials'] == 4
    protocol = chain.read(args.output/'prepared.json')
    assert any(row['path'].endswith('replay_codec_guarded_semantics.py') for row in protocol['algorithm'])
    assert chain._runner('semantic', chain.codec.VERSION) is chain.codec
    assert chain._runner('semantic', chain.semantic.VERSION) is chain.semantic


def test_native_replay_requires_whole_protocol_identity_and_keeps_cost_separate(tmp_path):
    args = prepared_sources(tmp_path)
    args.reuse_relations = tmp_path/'old'
    cases = ['a', 'b', 'c', 'd']
    for name, source, cost in [('documentation', args.defaults, 2), ('stream', args.stream, 4)]:
        target = args.reuse_relations/name
        chain.write(target/'prepared.json', chain.read(source/'prepared.json'))
        chain.write(target/'seal.json', chain.frozen(target/'prepared.json'))
        chain.write(target/'summary.json', dict(version=chain.REGISTRY[name].VERSION,
            native_executions=cost, results=[dict(case=case, alert={'program': name} if case == 'a' else None) for case in cases]))
    assert chain.prepare(args)['trials'] == 4
    chain.write(args.output/'semantic/summary.json', dict(decisions=[], first_stage_calls=1,
        first_stage_tokens=20, entire_second_gate_experiment_cost=dict(calls=1, tokens=30),
        compatible_cached_reviews=1, compatible_cached_review_tokens=30))
    result = chain.run(SimpleNamespace(input=args.output))
    assert result['fresh_native_executions'] == 0
    assert result['replayed_native_executions'] == 6
    assert result['alerts'] == 1
    changed = chain.read(args.defaults/'prepared.json')
    changed['changed_budget'] = 4
    with pytest.raises(ValueError, match='identical complete component protocol'):
        chain._replay_summary(args.reuse_relations/'documentation', changed)
