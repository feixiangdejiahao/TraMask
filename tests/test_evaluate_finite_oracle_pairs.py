"""Independent paired evaluation invariants, using local synthetic responses."""
import copy
import json
from pathlib import Path

import pytest

from anchor_retrieval.syntax import Source
from experimental.finite_oracle_questions import build_question, validate_question
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from scripts.evaluate_finite_oracle_pairs import (
    ARMS, evaluate, sha, verify_prepared,
)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n')


def reseal(root):
    write(root / 'seal.json', dict(files_sha256={str(path.relative_to(root)):sha(path)
        for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'seal.json'
        and 'completion' not in path.parts}))


def fixture(tmp_path):
    root, inventory = tmp_path / 'prepared', tmp_path / 'inventory'
    case = 'toy'
    code = '''def test_history():
    label = "你好"
    value = 2
    stable = 7
    assert value == 2
    value = 2
    assert value == 2
    assert all(v >= 0 for v in [value])
'''
    front = extract_frontend([Source('test_history.py', code, 'python')])
    corpus = to_emitter_corpus(front)
    base = next(iter(corpus['tests']))
    start = code.encode().index(b'value = 2') + len(b'value = ')
    candidates = [dict(id='variant_' + str(value), base_test_id=base, imports=[],
        source_test_ids=[], source_contexts=[], edits=[dict(role='input', before='2', after=str(value),
            span=dict(path='test_history.py', start_byte=start, end_byte=start + 1))]) for value in (2, 3)]
    for name, value in [('corpus.json', corpus), ('frontend.json', front),
                        ('source_pool.json', dict(candidates=candidates)), ('case.json', dict(id=case))]:
        write(inventory / case / name, value)
    issue = inventory / case / 'issue.md'
    issue.write_text('Assignment stores the given integer. Later assignment restores two.\n')
    settings = dict(model='deepseek-v4-flash', temperature=0, max_tokens=16384,
        response_format=dict(type='json_object'), stream=False, thinking=dict(type='enabled'))
    requests, arms = {}, {}
    for arm in ARMS:
        request = build_question(corpus, front, candidates, issue.read_text(), representation=arm)
        request['source_prepared'] = str((inventory / case).resolve())
        requests[arm] = request
        destination = root / case / arm
        write(destination / 'request.json', request)
        wire = {**settings, 'messages':[dict(role='system', content=request['system']),
                                       dict(role='user', content=request['prompt'])]}
        write(destination / 'wire_preview.json', wire)
        arms[arm] = dict(request=str((destination / 'request.json').resolve()),
            request_sha256=sha(destination / 'request.json'),
            wire_preview=str((destination / 'wire_preview.json').resolve()),
            wire_preview_sha256=sha(destination / 'wire_preview.json'))
    protocol = dict(arms=list(ARMS), cases=[case], inventory=str(inventory.resolve()), code_sha256={},
        model_settings=settings, input_sha256={case:{path.name:sha(path) for path in (inventory / case).iterdir()}})
    write(root / 'protocol.json', protocol)
    record = dict(case=case, status='offerable', arms=arms, members=2,
        member_ids=[row['id'] for row in candidates], family_id=requests['template']['family_id'],
        issue_source=str(issue.resolve()), issue_sha256=sha(issue))
    write(root / 'ready.json', dict(protocol_sha256=sha(root / 'protocol.json'), records=[record],
        totals=dict(offerable_pairs=1, members_per_arm=2)))
    reseal(root)
    return root, corpus, requests


def kept(alias):
    return dict(candidate=alias, status='keep', updates=[], basis='The original expectation applies.')


def revised(alias='C1', code='assert value == 3'):
    return dict(candidate=alias, status='revise', updates=[dict(assertion='A0', code=code)],
                basis='The edited initial assignment stores three.')


def fake_complete(root, corpus, request, arm, rows):
    destination = root / 'toy' / arm / 'completion'
    answer = json.dumps(dict(results=rows))
    response = dict(model='deepseek-v4-flash', choices=[dict(finish_reason='stop', message=dict(content=answer))])
    write(destination / 'request.json', json.loads((root / 'toy' / arm / 'wire_preview.json').read_text()))
    write(destination / 'response.body', response)
    write(destination / 'response.json', response)
    (destination / 'completion.txt').write_text(answer)
    write(destination / 'manifest.json', dict(status='complete', model='deepseek-v4-flash', request_id=request['id'],
        request_sha256=sha(destination / 'request.json'), response_sha256=sha(destination / 'response.body'),
        external_model_calls=1, finish_reason='stop', seconds=1.25,
        usage=dict(prompt_tokens=100, completion_tokens=20)))
    write(destination / 'validation.json', validate_question(request, answer, corpus))


def test_pending_members_remain_unanswered_without_implied_oracles(tmp_path):
    root, _, _ = fixture(tmp_path)
    result = evaluate(root)
    for arm in ARMS:
        counts = result['summary']['counts'][arm]
        assert counts['model_statuses'] == {'unanswered':2}
        assert counts['structurally_accepted'] == 0
        assert counts['semantic_verdicts'] == {'unreviewed':2}
    assert result['summary']['main_campaign_credit'] == 0
    assert all(row['proposed_test_sha256'] is None for row in result['review_template']['reviews'])


def test_structural_acceptance_never_becomes_automatic_semantic_credit(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    for arm in ARMS:
        fake_complete(root, corpus, requests[arm], arm, [kept('C0'), revised()])
    result = evaluate(root)
    for arm in ARMS:
        counts = result['summary']['counts'][arm]
        assert counts['structurally_accepted'] == 2 and counts['accepted_revisions'] == 1
        assert counts['correct_and_structurally_accepted'] == 0
        assert counts['semantic_verdicts'] == {'unreviewed':2}
        assert counts['prompt_tokens'] == 100 and counts['completion_tokens'] == 20
    member = result['packets'][0]['members'][1]
    assert len(member['original_assertions']) == 3
    assert member['input_test'].count('assert value == 2') == 2
    assert member['arms']['template']['accepted_test'].count('assert value == 2') == 1
    assert 'assert all(v >= 0 for v in [value])' in member['arms']['template']['accepted_test']


def test_manual_complete_review_is_bound_to_actual_response_and_program(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    for arm in ARMS:
        fake_complete(root, corpus, requests[arm], arm, [kept('C0'), revised()])
    result = evaluate(root)
    ledger = copy.deepcopy(result['review_template'])
    for row in ledger['reviews']:
        row.update(verdict='correct', reason='Reviewed every assertion and assignment in the complete test.')
    scored = evaluate(root, ledger)
    for arm in ARMS:
        assert scored['summary']['counts'][arm]['semantic_verdicts'] == {'correct':2}
        assert scored['summary']['counts'][arm]['entire_family_correct'] == 1
    ledger['reviews'][0]['response_sha256'] = 'other-response'
    with pytest.raises(ValueError, match='Semantic review evidence changed'):
        evaluate(root, ledger)


def test_correct_semantic_review_and_interface_rejection_are_separate(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template',
                  [kept('C0'), revised(code='assert value == 3 and stable == 7')])
    result = evaluate(root)
    ledger = copy.deepcopy(result['review_template'])
    row = next(row for row in ledger['reviews'] if row['candidate_id'] == 'variant_3' and row['arm'] == 'template')
    row.update(verdict='correct', reason='Both known assignments hold; this is a hypothetical manual judgment.')
    scored = evaluate(root, ledger)
    assert scored['summary']['counts']['template']['semantic_verdicts']['correct'] == 1
    assert scored['summary']['counts']['template']['correct_and_structurally_accepted'] == 0
    rejected = scored['packets'][0]['members'][1]['arms']['template']
    assert rejected['recorded_structural_status'] == 'rejected_structure'
    assert rejected['accepted_test'] is None and rejected['proposed_test'] is not None


def test_unknown_and_missing_rows_cannot_be_reviewed_as_correct_complete_oracles(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template',
                  [dict(candidate='C0', status='unknown', updates=[], basis='Insufficient source contract.')])
    result = evaluate(root)
    assert result['summary']['counts']['template']['model_statuses'] == {'unknown':1, 'unanswered':1}
    ledger = result['review_template']
    ledger['reviews'][0].update(verdict='correct', reason='Would incorrectly grant missing oracle credit.')
    with pytest.raises(ValueError, match='Missing or unknown answer'):
        evaluate(root, ledger)


def test_malformed_member_does_not_erase_other_members_independent_evidence(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template',
        [dict(candidate='C0', status=[], updates=[], basis='Malformed status.'), kept('C1')])
    result = evaluate(root)
    assert result['summary']['counts']['template']['model_statuses'] == {'invalid_answer':1, 'keep':1}
    assert result['summary']['counts']['template']['structurally_accepted'] == 1


@pytest.mark.parametrize('declared', ['keep', 'revise'])
def test_missing_basis_preserves_explicit_complete_oracle_but_not_interface_acceptance(tmp_path, declared):
    root, corpus, requests = fixture(tmp_path)
    row = kept('C0') if declared == 'keep' else revised()
    del row['basis']
    fake_complete(root, corpus, requests['template'], 'template',
                  [row, kept('C1')] if declared == 'keep' else [kept('C0'), row])
    result = evaluate(root)
    index = 0 if declared == 'keep' else 1
    member = result['packets'][0]['members'][index]['arms']['template']
    assert member['model_status'] == member['recorded_structural_status'] == 'invalid_answer'
    assert member['explicit_oracle_status'] == declared
    assert member['proposed_test'] is not None and member['accepted_test'] is None
    ledger = result['review_template']
    candidate_id = 'variant_2' if declared == 'keep' else 'variant_3'
    review = next(row for row in ledger['reviews'] if row['arm'] == 'template' and row['candidate_id'] == candidate_id)
    review.update(verdict='correct', reason='Synthetic human review illustrates that a prose field is not oracle content.')
    scored = evaluate(root, ledger)
    assert scored['summary']['counts']['template']['semantic_verdicts']['correct'] == 1
    assert scored['summary']['counts']['template']['correct_and_structurally_accepted'] == 0


def test_undeclared_missing_answer_cannot_be_promoted_by_validation_artifact(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template', [kept('C0')])
    path = root / 'toy' / 'template' / 'completion' / 'validation.json'
    value = json.loads(path.read_text())
    value['members'][1]['status'] = 'keep'
    write(path, value)
    with pytest.raises(ValueError, match='Unknown/omitted answer claimed valid coverage'):
        evaluate(root)


def test_actual_wire_settings_must_match_frozen_preview_even_with_a_new_hash(tmp_path):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template', [kept('C0'), revised()])
    folder = root / 'toy' / 'template' / 'completion'
    wire = json.loads((folder / 'request.json').read_text()); wire['temperature'] = 1
    write(folder / 'request.json', wire)
    manifest = json.loads((folder / 'manifest.json').read_text())
    manifest['request_sha256'] = sha(folder / 'request.json'); write(folder / 'manifest.json', manifest)
    with pytest.raises(ValueError, match='Actual wire differs'):
        evaluate(root)


def test_pair_identity_is_recomputed_instead_of_trusting_saved_audit_boolean(tmp_path):
    root, _, _ = fixture(tmp_path)
    path = root / 'toy' / 'expanded' / 'request.json'
    request = json.loads(path.read_text()); payload = json.loads(request['prompt'])
    payload['test_source'][0]['modified_test'] += '\n# unrelated difference\n'
    request['prompt'] = json.dumps(payload); write(path, request)
    wire_path = root / 'toy' / 'expanded' / 'wire_preview.json'
    wire = json.loads(wire_path.read_text()); wire['messages'][1]['content'] = request['prompt']; write(wire_path, wire)
    ready = json.loads((root / 'ready.json').read_text())
    ready['records'][0]['arms']['expanded'].update(request_sha256=sha(path), wire_preview_sha256=sha(wire_path))
    write(root / 'ready.json', ready); reseal(root)
    with pytest.raises(ValueError, match='Source expansion differs'):
        verify_prepared(root)


@pytest.mark.parametrize('change', ['imports', 'extra_input_edit', 'duplicate_member'])
def test_accepted_artifact_cannot_change_context_or_member_inventory(tmp_path, change):
    root, corpus, requests = fixture(tmp_path)
    fake_complete(root, corpus, requests['template'], 'template', [kept('C0'), revised()])
    path = root / 'toy' / 'template' / 'completion' / 'validation.json'
    value = json.loads(path.read_text())
    if change == 'imports':
        value['revisions'][0]['imports'] = [dict(name='bad', module='wrong')]
    elif change == 'extra_input_edit':
        value['revisions'][0]['edits'].append(copy.deepcopy(value['revisions'][0]['edits'][0]))
    else:
        value['members'].append(copy.deepcopy(value['members'][0]))
    write(path, value)
    with pytest.raises(ValueError):
        evaluate(root)
