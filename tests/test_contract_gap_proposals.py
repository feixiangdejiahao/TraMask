import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import contract_gap_proposals as baseline
from relation_search import compact_contract_guarded, oracle
from generic_composition.emitter import emit


SAMPLES = {
    'python': ('test_value.py', 'from api import double\n'
        'def test_value():\n    assert double(3) == 6\n',
        ('api.py', 'def double(value):\n    """Return twice the input."""\n    return PRIVATE_BODY(value)\n')),
    'go': ('value_test.go', 'package value\nimport "testing"\n'
        'func TestValue(t *testing.T) { if double(3) != 6 { t.Fatal("wrong") } }\n',
        ('value.go', 'package value\n// double returns twice its input.\nfunc double(value int) int { return value*2 }\n')),
    'typescript': ('value.test.ts', 'import {it,expect} from "vitest";\nimport {double} from "./api";\n'
        'it("value", () => { expect(double(3)).toBe(6); });\n',
        ('api.ts', '/** Return twice the input. */\nexport function double(value:number) { return value*2; }\n')),
}


def fixture(language='python', code=None, extra=()):
    path, original, api = SAMPLES[language]
    sources = [Source(path, code or original, language, 'repository'),
               Source(api[0], api[1], language, 'repository')]
    sources.extend(extra)
    frontend = extract_frontend(sources)
    return to_emitter_corpus(frontend), frontend


def prepare(language='python', code=None, **kwargs):
    corpus, frontend = fixture(language, code)
    result = baseline.prepare(corpus, frontend, 'The public API returns twice the input.', **kwargs)
    assert result['status'] == 'prepared'
    return corpus, frontend, result


def shown(prepared, alias='S1'):
    return next(row['context'] for row in json.loads(prepared['request']['prompt'])['seeds'] if row['seed_alias'] == alias)


def answer(rewritten, alias='S1'):
    return json.dumps(dict(tests=[dict(seed_alias=alias, rewritten_test=rewritten)]), ensure_ascii=False)


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_identity_context_and_complete_rewrite_work_in_each_language(language):
    corpus, frontend, prepared = prepare(language)
    context = shown(prepared)
    original = context['original_test']
    assert original == context['modified_test']
    assert context['input_edits'] == []
    assert isinstance(context['source_analysis'], str) and context['source_analysis']
    assert 'api_contract_context' in context
    replacement = original.replace('double(3)', 'double(4)').replace('!= 6', '!= 8').replace('== 6', '== 8').replace('toBe(6)', 'toBe(8)')
    result = baseline.decide(corpus, frontend, prepared, answer(replacement))
    assert result['status'] == 'decoded' and not result['rejected']
    candidate = result['candidates'][0]
    assert candidate['order'] == [1]
    assert len(candidate['edits']) == 1 and candidate['edits'][0]['role'] == 'program'
    assert oracle.preview(corpus, candidate) == replacement
    # A separate gate gets only actual code and source, never a generation basis.
    gate = compact_contract_guarded.prepare(corpus, frontend, candidate,
        'The public API returns twice the input.', max_prompt_bytes=96000)
    assert gate['status'] == 'prepared'
    payload = json.loads(gate['request']['prompt'])
    assert payload['modified_test'] == replacement and payload['original_test'] == original
    assert 'basis' not in candidate
    assert not result['alarm_eligible'] and result['semantic_validity'] == 'unconfirmed'
    emitted = emit(corpus, [candidate])
    assert emitted['unsupported'] == []


def test_projection_removes_historical_metadata_and_never_sends_labels_or_outcomes():
    historical = Source('test_history.py', 'def test_history():\n    assert PRIVATE_HISTORY\n', 'python', 'trajectory')
    corpus, frontend = fixture(extra=[historical])
    corpus['evaluation_label'] = 'PRIVATE_LABEL'
    frontend['native_result'] = 'PRIVATE_FAILURE'
    before = copy.deepcopy((corpus, frontend))
    prepared = baseline.prepare(corpus, frontend, 'Twice the input.\n## Recommended Workflow\nPRIVATE_WORKFLOW\n## Command Execution Rules\nPRIVATE_WORKFLOW')
    prompt = prepared['request']['prompt']
    assert all(marker not in prompt for marker in ('PRIVATE_HISTORY', 'PRIVATE_LABEL', 'PRIVATE_FAILURE', 'PRIVATE_WORKFLOW', 'PRIVATE_BODY'))
    assert 'test_history.py' not in prompt
    assert prepared['repository_test_count'] == 1
    assert (corpus, frontend) == before


def test_seed_order_is_frozen_first_four_and_budget_omits_whole_context_without_refill():
    code = 'from api import double\n' + '\n'.join(
        f'def test_value_{index}():\n    assert double({index}) == {index*2}\n' for index in range(6))
    corpus, frontend = fixture(code=code)
    ordered = sorted(corpus['tests'], key=lambda key: corpus['tests'][key]['span']['start_byte'])
    for index, key in enumerate(reversed(ordered)):
        corpus['tests'][key]['retrieval_rank'] = index
    prepared = baseline.prepare(corpus, frontend, 'Twice the input.')
    assert [seed['base_test_id'] for seed in prepared['seeds']] == list(reversed(ordered))[:4]
    assert prepared['selected_seed_count'] == 4 and prepared['unselected_seed_count'] == 2
    request = prepared['request']
    exact = baseline.prepare(corpus, frontend, 'Twice the input.', max_prompt_bytes=request['prompt_bytes'])
    assert exact['request'] == request
    tiny = baseline.prepare(corpus, frontend, 'Twice the input.', max_prompt_bytes=1)
    assert tiny['request'] is None and tiny['status'] == 'no_complete_seed_context'
    assert len(tiny['omitted']) == 4 and tiny['unselected_seed_count'] == 2
    assert all(row['reason'] == 'whole_context_prompt_budget' for row in tiny['omitted'])
    assert tiny['truncated'] is False


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_registration_and_signature_changes_are_rejected(language):
    corpus, frontend, prepared = prepare(language)
    original = shown(prepared)['original_test']
    replacement = original.replace('test_value', 'test_other').replace('TestValue', 'TestOther').replace('"value"', '"other"')
    result = baseline.decide(corpus, frontend, prepared, answer(replacement))
    assert result['candidates'] == []
    assert result['rejected'][0]['reason'] == 'registration_signature_or_decorators_changed'


def test_python_decorators_and_utf8_byte_spans_are_preserved():
    code = 'from api import double\nimport pytest\n# 中文 before byte positions\n' \
        '@pytest.mark.parametrize("value", [3, 4])\ndef test_value(value):\n    assert double(value) == value * 2\n'
    corpus, frontend, prepared = prepare(code=code)
    original = shown(prepared)['original_test']
    rewritten = original.replace('    assert', '    label = "中文"\n    assert')
    result = baseline.decide(corpus, frontend, prepared, answer(rewritten))
    assert len(result['candidates']) == 1
    assert oracle.preview(corpus, result['candidates'][0]) == rewritten
    changed_decorator = rewritten.replace('[3, 4]', '[8, 9]')
    assert not baseline.decide(corpus, frontend, prepared, answer(changed_decorator))['candidates']


@pytest.mark.parametrize('suffix', [
    '\ndef test_other():\n    assert True',
    '\nclass Added:\n    pass',
    '\nassert False',
])
def test_rewrite_cannot_escape_its_complete_original_python_test(suffix):
    corpus, frontend, prepared = prepare()
    rewritten = shown(prepared)['original_test'] + suffix
    result = baseline.decide(corpus, frontend, prepared, answer(rewritten))
    assert not result['candidates']
    assert result['rejected'][0]['reason'] == 'replacement_escapes_original_test'


@pytest.mark.parametrize(('statement', 'reason'), [
    ('import socket', 'imports_or_scope_directives_changed'),
    ('global object_value', 'imports_or_scope_directives_changed'),
    ('__import__("socket")', 'new_bound_dynamic_process_or_network_call_requires_scope_review'),
    ('eval("1+1")', 'new_bound_dynamic_process_or_network_call_requires_scope_review'),
])
def test_import_scope_and_bound_dynamic_boundaries_are_withheld(statement, reason):
    corpus, frontend, prepared = prepare()
    original = shown(prepared)['original_test']
    rewritten = original.replace('    assert', '    ' + statement + '\n    assert')
    result = baseline.decide(corpus, frontend, prepared, answer(rewritten))
    assert not result['candidates']
    assert result['rejected'][0]['reason'] == reason


def test_import_text_and_local_resource_observations_do_not_invent_external_io():
    code = 'from api import double\ndef test_value(tmp_path):\n' \
        '    target = tmp_path / "result.txt"\n    target.write_text("same")\n    assert double(3) == 6\n'
    corpus, frontend, prepared = prepare(code=code)
    original = shown(prepared)['original_test']
    rewritten = original.replace('    assert', '    text = "import socket"\n    assert')
    result = baseline.decide(corpus, frontend, prepared, answer(rewritten))
    assert len(result['candidates']) == 1
    changed_io = rewritten.replace('write_text("same")', 'write_text("changed")')
    assert baseline.decide(corpus, frontend, prepared, answer(changed_io))['candidates']


@pytest.mark.parametrize('response', [
    '{"tests":[],"tests":[]}', '{"tests":[],"basis":"anything"}',
    '{"tests":[{"seed_alias":"S1","rewritten_test":"x","basis":"anything"}]}',
    '{"tests":[{"seed_alias":"S1","rewritten_test":"x","rewritten_test":"y"}]}',
    '{"tests":NaN}', '```json\n{"tests":[]}\n```',
    json.dumps({'tests':[dict(seed_alias='S1',rewritten_test='x')]*4}),
])
def test_malformed_or_over_budget_response_is_not_repaired(response):
    corpus, frontend, prepared = prepare()
    result = baseline.decide(corpus, frontend, prepared, response)
    assert result['status'] == 'unknown' and not result['candidates']


def test_alias_duplicates_and_response_order_do_not_trigger_refill_or_repair():
    corpus, frontend, prepared = prepare()
    original = shown(prepared)['original_test']
    rewritten = original.replace('double(3) == 6', 'double(4) == 8')
    response = json.dumps(dict(tests=[dict(seed_alias='missing',rewritten_test=rewritten),
        dict(seed_alias='S1',rewritten_test=rewritten), dict(seed_alias='S1',rewritten_test=rewritten)]))
    result = baseline.decide(corpus, frontend, prepared, response)
    assert len(result['candidates']) == 1 and result['candidates'][0]['order'] == [2]
    assert [row['reason'] for row in result['rejected']] == ['unknown_seed_alias','duplicate_proposal']
    assert baseline.decide(corpus, frontend, prepared, '{"tests":[]}')['status'] == 'decoded'
    incomplete = baseline.decide(corpus, frontend, prepared, response, finish_reason='length')
    assert incomplete['status'] == 'unknown' and not incomplete['candidates']


def test_source_and_request_receipts_reject_changes():
    corpus, frontend, prepared = prepare()
    rewritten = shown(prepared)['original_test'].replace('double(3) == 6', 'double(4) == 8')
    changed = copy.deepcopy(prepared)
    changed['request']['prompt'] += ' '
    with pytest.raises(ValueError, match='request_identity'):
        baseline.decide(corpus, frontend, changed, answer(rewritten))
    corpus['sources']['api.py']['code'] += '\n'
    with pytest.raises(ValueError, match='source_snapshot'):
        baseline.decide(corpus, frontend, prepared, answer(rewritten))


def test_existing_codec_guard_does_not_filter_identity_context(monkeypatch):
    corpus, frontend = fixture()
    monkeypatch.setattr(compact_contract_guarded, 'prepare', lambda *args, **kwargs: pytest.fail('Generation used the admission guard'))
    assert baseline.prepare(corpus, frontend, 'Twice the input.')['status'] == 'prepared'


def test_explicitly_incomplete_file_is_not_promoted_by_metadata_refresh():
    corpus, frontend = fixture()
    corpus['sources']['test_value.py']['complete_file'] = False
    prepared = baseline.prepare(corpus, frontend, 'Twice the input.')
    assert prepared['status'] == 'no_complete_seed_context'
    assert prepared['omitted'][0]['reason'] == 'complete_repository_source_required'


def test_invalid_full_syntax_is_rejected_without_altering_original_bytes():
    corpus, frontend, prepared = prepare()
    previous = copy.deepcopy((corpus, frontend, prepared))
    rewritten = shown(prepared)['original_test'].replace('assert double(3) == 6', 'if (')
    result = baseline.decide(corpus, frontend, prepared, answer(rewritten))
    assert result['candidates'] == []
    assert result['rejected'][0]['reason'] == 'rewritten_source_parse_error'
    assert (corpus, frontend, prepared) == previous


def test_helper_and_large_original_test_suffix_are_not_truncated():
    code = 'from api import double\n' \
        'def verify(value):\n    assert double(value) == value * 2\n' \
        'def test_value():\n    marker = "' + '中文' * 600 + '"\n    verify(3)\n    assert double(4) == 8\n'
    corpus, frontend, prepared = prepare(code=code)
    context = shown(prepared)
    assert '中文' * 600 in context['original_test']
    assert context['original_test'].endswith('assert double(4) == 8')
    assert 'def verify(value):\n    assert double(value) == value * 2' in context['source_analysis']
    assert prepared['request']['prompt_bytes'] == len(prepared['request']['system'].encode()) + len(prepared['request']['prompt'].encode())


def test_subject_method_names_do_not_imply_io_and_aliased_code_loaders_are_detected():
    code = 'from api import double\nfrom importlib import import_module as load\n' \
        'def test_value(subject):\n    assert double(3) == 6\n'
    corpus, frontend, prepared = prepare(code=code)
    original = shown(prepared)['original_test']
    ordinary = original.replace('    assert', '    subject.run()\n    text = "ab".replace("a", "c")\n    assert')
    assert baseline.decide(corpus, frontend, prepared, answer(ordinary))['candidates']
    dynamic = original.replace('    assert', '    load("socket")\n    assert')
    result = baseline.decide(corpus, frontend, prepared, answer(dynamic))
    assert result['rejected'][0]['reason'] == 'new_bound_dynamic_process_or_network_call_requires_scope_review'
    assert result['rejected'][0]['status'] == 'scope_unknown'


def test_new_parser_strings_regex_compile_and_file_observations_remain_candidates():
    code = 'from api import double\nimport re\n' \
        'def test_value(resource):\n    assert double(3) == 6\n'
    corpus, frontend, prepared = prepare(code=code)
    rewritten = shown(prepared)['original_test'].replace('    assert',
        '    url_input = "https://parser.example/value"\n    path_input = "/tmp/parser-value"\n'
        '    parsed = re.compile("x+")\n    snapshot = resource.read_bytes()\n    assert')
    assert baseline.decide(corpus, frontend, prepared, answer(rewritten))['candidates']


def test_issue_api_catalog_retrieves_uncalled_exact_names_and_preserves_qualification():
    sources = [
        Source('api.py', 'def new_operation(value):\n    """Public new operation contract."""\n    return PRIVATE_NEW_BODY(value)\n'
            'class Shape:\n    """Public shape contract."""\n    PRIVATE_FIELD = factory()\n'
            '    def check(self, value):\n        return PRIVATE_METHOD_BODY(value)\n', 'python', 'repository'),
        Source('other.py', 'def new_operation(value, option=False):\n    return PRIVATE_OTHER_BODY(value)\n', 'python', 'repository'),
        Source('test_api.py', 'def new_operation():\n    return PRIVATE_TEST_HELPER\n', 'python', 'repository'),
        Source('history.py', 'def new_operation():\n    return PRIVATE_HISTORY\n', 'python', 'trajectory'),
    ]
    frontend = extract_frontend(sources);corpus = to_emitter_corpus(frontend)
    catalog = baseline.issue_api_catalog(corpus, 'Shape and check need new_operation. xnew_operation_suffix is not a match.')
    assert [row['symbol'] for row in catalog['entries']] == ['Shape','check','new_operation','new_operation']
    assert catalog['entries'][1]['qualification'] == ['Shape','check']
    assert all('PRIVATE_' not in json.dumps(row) for row in catalog['entries'])
    assert all(row['declaration']['path'] not in {'test_api.py','history.py'} for row in catalog['entries'])
    assert catalog['entries'][0]['documentation'][0]['text'] == '"""Public shape contract."""'
    assert baseline.issue_api_catalog(corpus, 'xnew_operation_suffix')['entries'] == []
    omitted = baseline.issue_api_catalog(corpus, 'new_operation', max_bytes=1)
    assert not omitted['entries'] and len(omitted['omitted']) == 2 and not omitted['truncated']


@pytest.mark.parametrize(('language','path','code','issue','expected','absent'), [
    ('go','api.go','package api\n// Config describes the values.\ntype Config struct { Name string; Enabled bool }\n'
     'func (c *Config) Apply(value string) string { return PRIVATE_IMPL(value) }\n',
     'Apply Config', ['Apply','Config'], 'PRIVATE_IMPL'),
    ('typescript','api.ts','/** Public options. */\nexport interface Options {enabled:boolean}\n'
     '/** Public new call. */\nexport const newCall = (value:Options):boolean => { return PRIVATE_IMPL(value); };\n',
     'newCall Options', ['newCall','Options'], 'PRIVATE_IMPL'),
])
def test_issue_api_catalog_keeps_go_layout_and_typescript_arrow_headers(language,path,code,issue,expected,absent):
    frontend = extract_frontend([Source(path,code,language,'repository')]);corpus=to_emitter_corpus(frontend)
    catalog = baseline.issue_api_catalog(corpus,issue)
    assert [row['symbol'] for row in catalog['entries']] == expected
    assert absent not in json.dumps(catalog)
    assert all(row['declaration']['text'] for row in catalog['entries'])


def test_uncalled_issue_api_headers_share_the_single_total_prompt_budget():
    corpus, frontend = fixture()
    api = corpus['sources']['api.py']['code'] + '\ndef added_api(value):\n    """A new public operation."""\n    return PRIVATE_ADDED_IMPL(value)\n'
    frontend = extract_frontend([Source('test_value.py',corpus['sources']['test_value.py']['code'],'python','repository'),
        Source('api.py',api,'python','repository')]);corpus=to_emitter_corpus(frontend)
    prepared = baseline.prepare(corpus,frontend,'The added_api contract is new.')
    payload = json.loads(prepared['request']['prompt'])
    assert [row['symbol'] for row in payload['issue_api_catalog']['entries']] == ['added_api']
    assert 'PRIVATE_ADDED_IMPL' not in prepared['request']['prompt']
    assert prepared['prompt_bytes'] <= 96000
    exact = baseline.prepare(corpus,frontend,'The added_api contract is new.',max_prompt_bytes=prepared['prompt_bytes'])
    assert exact['request'] == prepared['request']
    refused = baseline.prepare(corpus,frontend,'The added_api contract is new.',max_prompt_bytes=prepared['prompt_bytes']-1)
    assert refused['request'] is None and len(refused['omitted']) == 1
