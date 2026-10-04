import copy
import json

import pytest

from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend, to_emitter_corpus
from relation_search import contract_gap_proposals as core
from relation_search import declaration_contract_planning as planner
from relation_search import planned_contract_gap_proposals as generated
from relation_search import csi_repair_transport, oracle


def fixture(language='python', api=None):
    samples = {
        'python': ('test_value.py', 'from api import twice\ndef test_value():\n    assert twice(3) == 6\n',
                   'api.py', '# A public token.\nTOKEN = "PRIVATE_INITIALIZER"\n'
                   'def twice(n):\n    """Return twice n."""\n    return PRIVATE_BODY(n)\n'),
        'go': ('value_test.go', 'package value\nimport "testing"\n'
               'func TestValue(t *testing.T) { if Twice(3) != 6 { t.Fatal("wrong") } }\n',
               'value.go', 'package value\n// Box supplies a complete owner contract.\n'
               '// Completion is synchronous.\ntype Box struct {\n// Size is public.\nSize int\nprivate int\n}\n'
               '// Twice returns twice n.\nfunc Twice(n int) int { return n*2 }\n'
               '// Read returns the observation.\nfunc (b *Box) Read() int { return PRIVATE_BODY() }\n'
               '// Ready selects synchronous mode.\nvar Ready = &Box{Size: 1}\n'),
        'typescript': ('value.test.ts', 'import {it,expect} from "vitest";\nimport {twice} from "./api";\n'
                       'it("value", () => { expect(twice(3)).toBe(6); });\n', 'api.ts',
                       '/** Return twice n. */\nexport const twice = (n:number):number => { return PRIVATE_BODY(n); };\n'
                       '/** Public option. */\nexport const READY = PRIVATE_INITIALIZER;\n'
                       'const PRIVATE = 1;\nexport interface Box { size:number; }\n'),
    }
    path, code, api_path, default_api = samples[language]
    frontend = extract_frontend([Source(path, code, language, 'repository'),
        Source(api_path, api or default_api, language, 'repository')])
    corpus = to_emitter_corpus(frontend)
    inherited = core.prepare(corpus, frontend, 'twice Twice Read return their documented numeric value.')
    return corpus, frontend, inherited


def choose(prepared, symbol, **match):
    shown = {entry['id'] for entry in prepared['presented']}
    return next(row['id'] for row in prepared['records'] if row['symbol'] == symbol and row['id'] in shown
                and all(row.get(k) == v for k, v in match.items()))


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_directory_has_complete_tests_exact_source_receipts_and_no_implementation(language):
    corpus, _, inherited = fixture(language)
    before = copy.deepcopy(inherited)
    prepared = planner.prepare(corpus, inherited)
    payload = json.loads(prepared['request']['prompt'])
    old = json.loads(inherited['request']['prompt'])
    assert payload['original_tests'] == [dict(seed_alias=s['seed_alias'], original_test=s['context']['original_test']) for s in old['seeds']]
    assert 'PRIVATE_BODY' not in prepared['request']['prompt']
    assert 'PRIVATE_INITIALIZER' not in prepared['request']['prompt']
    assert 'source_analysis' not in prepared['request']['prompt']
    assert prepared['request']['max_tokens'] == 8192 and prepared['request']['reasoning_effort'] == 'high'
    assert prepared['request']['prompt_bytes'] <= 96000 and prepared['catalog_bytes'] <= 64000
    for record in prepared['records']:
        raw = corpus['sources'][record['path']]['code'].encode()
        assert raw[record['start_byte']:record['end_byte']].decode() == record['text']
        for doc in record['documentation']:
            assert raw[doc['start_byte']:doc['end_byte']].decode() == doc['text']
    assert inherited == before


def test_go_parent_documentation_and_globals_are_complete_single_spans():
    corpus, _, inherited = fixture('go')
    prepared = planner.prepare(corpus, inherited)
    box = next(r for r in prepared['records'] if r['symbol'] == 'Box')
    assert len(box['documentation']) == 1
    assert 'Completion is synchronous.' in box['documentation'][0]['text']
    assert 'private int' not in box['text']
    ready = next(r for r in prepared['records'] if r['symbol'] == 'Ready')
    assert 'selects synchronous mode' in ready['documentation'][0]['text']
    assert '&Box' not in ready['text']
    identifier = choose(prepared, 'Read')
    selected = planner.decode(prepared, json.dumps({'ids': [identifier]}))
    result = planner.generation_preparation(inherited, prepared, selected)
    entries = json.loads(result['request']['prompt'])['issue_api_catalog']['entries']
    assert {e['symbol'] for e in entries} == {'Read', 'Box'}
    assert all(e['symbol'] != 'Size' for e in entries)  # no reverse field/member expansion


@pytest.mark.parametrize('content,finish', [
    ('{"ids":[]}', 'stop'), ('{"ids":[]}', 'length'), ('{"ids":', 'stop'),
    ('{"ids":[],"basis":"invented"}', 'stop'), ('{"ids":[],"ids":[]}', 'stop'),
    ('{"ids":["unknown"]}', 'stop'),
])
def test_unknown_empty_or_incomplete_plan_preserves_original_catalog_and_entire_request(content, finish):
    corpus, _, inherited = fixture()
    prepared = planner.prepare(corpus, inherited)
    decision = planner.decode(prepared, content, finish_reason=finish)
    result = planner.generation_preparation(inherited, prepared, decision)
    assert result['request'] == inherited['request']
    assert result['planning_context']['status'] == 'fallback'
    assert result['seeds'] == inherited['seeds'] and result['omitted'] == inherited['omitted']


def test_duplicate_or_omitted_ids_are_not_accepted():
    corpus, _, inherited = fixture()
    prepared = planner.prepare(corpus, inherited)
    identifier = choose(prepared, 'twice')
    assert planner.decode(prepared, json.dumps({'ids': [identifier, identifier]}))['status'] == 'unknown'
    tiny = planner.prepare(corpus, inherited, max_catalog_bytes=1)
    assert tiny['omitted'] and not tiny['presented'] and tiny['request'] is None
    assert planner.decode(tiny, json.dumps({'ids': [identifier]}))['status'] == 'unknown'


def test_zero_evidence_budget_falls_back_without_truncating_docs(monkeypatch):
    corpus, _, inherited = fixture()
    prepared = planner.prepare(corpus, inherited)
    choice = planner.decode(prepared, json.dumps({'ids': [choose(prepared, 'twice')]}))
    monkeypatch.setattr(planner, 'MAX_EVIDENCE_BYTES', 1)
    result = planner.generation_preparation(inherited, prepared, choice)
    assert result['request'] == inherited['request']
    assert result['planning_context']['evidence_ledger'][0]['included'] is False


@pytest.mark.parametrize('language', ['python', 'go', 'typescript'])
def test_planned_generation_keeps_contexts_body_guard_and_adds_exact_provenance(language):
    corpus, frontend, inherited = fixture(language)
    plan = planner.prepare(corpus, inherited)
    symbol = 'Twice' if language == 'go' else 'twice'
    selected = planner.decode(plan, json.dumps({'ids': [choose(plan, symbol)]}))
    prepared = planner.generation_preparation(inherited, plan, selected)
    payload = json.loads(prepared['request']['prompt'])
    assert payload['seeds'] == json.loads(inherited['request']['prompt'])['seeds']
    original = payload['seeds'][0]['context']['original_test']
    new = original.replace('(3)', '(4)').replace('== 6', '== 8').replace('!= 6', '!= 8').replace('toBe(6)', 'toBe(8)')
    response = json.dumps({'tests': [dict(seed_alias='S1', rewritten_test=new)]})
    decoded = generated.decide(corpus, frontend, prepared, response)
    candidate = decoded['candidates'][0]
    assert candidate['source_provenance']['source_file']['origin'] == 'repository'
    assert candidate['generator'] == core.VERSION
    assert oracle.preview(corpus, candidate) == new
    baseline = core.decide(corpus, frontend, prepared, response)['candidates'][0]
    assert {k: v for k, v in candidate.items() if k != 'source_provenance'} == baseline
    if language == 'python':
        assert csi_repair_transport.shape(new, 'test_value') != csi_repair_transport.shape(new.replace('twice(4)', 'twice(9)'), 'test_value')
    bad = json.dumps({'tests': [dict(seed_alias='S1', rewritten_test=new+'\ndef test_extra():\n    assert False')]})
    assert not generated.decide(corpus, frontend, prepared, bad)['candidates']


def test_names_do_not_filter_unmentioned_owners_or_claim_call_binding():
    api = 'class First:\n    def read(self):\n        """First contract."""\n        return 1\n' \
          'class Second:\n    def read(self):\n        """Second contract."""\n        return 2\n'
    corpus, frontend, _ = fixture(api=api)
    inherited = core.prepare(corpus, frontend, 'read returns the documented result.')
    prepared = planner.prepare(corpus, inherited)
    shown = {x['id'] for x in prepared['presented']}
    assert {r['owner'] for r in prepared['records'] if r['symbol'] == 'read' and r['id'] in shown} == {'First', 'Second'}
    assert 'not actual callee binding' in prepared['request']['prompt']


def test_changed_inherited_source_or_test_context_is_rejected():
    corpus, _, inherited = fixture()
    changed = copy.deepcopy(corpus)
    changed['sources']['api.py']['code'] += '\n# changed\n'
    with pytest.raises(ValueError, match='snapshot_changed'):
        planner.prepare(changed, inherited)


def test_typescript_public_global_rule_and_arrow_body_exclusion():
    corpus, _, inherited = fixture('typescript')
    prepared = planner.prepare(corpus, inherited)
    candidates = {r['id'] for r in prepared['candidates']}
    rows = {r['symbol']: r for r in prepared['records']}
    assert rows['READY']['id'] in candidates
    assert rows['PRIVATE']['id'] not in candidates
    assert 'PRIVATE_BODY' not in rows['twice']['text'] and '(n:number)' in rows['twice']['text']


def test_python_public_class_fields_keep_declared_owner_without_initializer():
    corpus, _, inherited = fixture(api='class Box:\n'
        '    # Public size limit.\n    size = PRIVATE_INITIALIZER\n'
        '    _internal = PRIVATE_INITIALIZER\n'
        '    def read(self):\n        local = PRIVATE_INITIALIZER\n        return local\n')
    prepared = planner.prepare(corpus, inherited)
    rows = {r['symbol']: r for r in prepared['records']}
    candidates = {r['id'] for r in prepared['candidates']}
    assert rows['size']['owner'] == 'Box' and rows['size']['owner_ids']
    assert rows['size']['id'] in candidates and rows['_internal']['id'] not in candidates
    assert 'PRIVATE_INITIALIZER' not in prepared['request']['prompt']
    assert 'local' not in rows


def test_typescript_public_field_initializer_body_is_opaque():
    corpus, _, inherited = fixture('typescript', api='export class Box {\n'
        '  /** A public action. */\n  action = (n:number) => { return PRIVATE_BODY(n); };\n'
        '  value = PRIVATE_INITIALIZER();\n}\n')
    prepared = planner.prepare(corpus, inherited)
    assert 'PRIVATE_BODY' not in prepared['request']['prompt']
    assert 'PRIVATE_INITIALIZER' not in prepared['request']['prompt']


def test_generic_receiver_does_not_bind_its_type_argument_as_owner():
    corpus, _, inherited = fixture('go', api='package value\n'
        '// Box owns observations.\ntype Box[T any] struct {}\n'
        '// T is an unrelated type.\ntype T int\n'
        '// Read returns a value.\nfunc (b *Box[T]) Read() int { return 1 }\n')
    prepared = planner.prepare(corpus, inherited)
    read = next(r for r in prepared['records'] if r['symbol'] == 'Read')
    assert read['owner'] == '' and read['owner_ids'] == []


def test_go_owner_documentation_does_not_cross_package_with_same_directory():
    corpus, frontend, _ = fixture('go')
    other = Source('other.go', 'package unrelated\n// WRONG_OWNER_DOC\ntype Box struct {}\n', 'go', 'repository')
    sources = [Source(path, row['code'], 'go', 'repository') for path, row in corpus['sources'].items()] + [other]
    frontend = extract_frontend(sources)
    corpus = to_emitter_corpus(frontend)
    inherited = core.prepare(corpus, frontend, 'Read returns its observation.')
    prepared = planner.prepare(corpus, inherited)
    selection = planner.decode(prepared, json.dumps({'ids': [choose(prepared, 'Read')]}))
    result = planner.generation_preparation(inherited, prepared, selection)
    assert 'WRONG_OWNER_DOC' not in json.dumps(json.loads(result['request']['prompt'])['issue_api_catalog'])
