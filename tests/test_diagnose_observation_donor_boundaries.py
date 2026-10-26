from anchor_retrieval.syntax import Source
from prototypes.observation_address_search import generate
from relational_gap.frontend import extract_frontend, to_emitter_corpus
import pytest

from scripts.diagnose_observation_donor_boundaries import diagnose, verify_census_seals
from tests.test_observation_address_join import GO, source


def prepare(code, language='python'):
    frontend = extract_frontend([Source('test_generic.py' if language=='python' else 'generic_test.go', code, language)])
    corpus = to_emitter_corpus(frontend)
    return corpus, frontend, generate(corpus, frontend)['demand_rows']


def test_diagnostic_reports_expression_closure_boundary_without_relaxing_it():
    corpus, frontend, demands = prepare(GO.replace('box.Put("a",1)', 'box.Put("a",int(1))'), 'go')
    result = diagnose(corpus, frontend, demands)
    assert result['counts'] == {'nonliteral_operation_argument': 1}
    args = result['calls'][0]['arguments']
    assert args[1]['source_text'] == 'int(1)'
    at = args[1]['span']
    assert corpus['sources'][at['path']]['code'].encode()[at['start_byte']:at['end_byte']].decode() == 'int(1)'


def test_demand_field_filters_source_writers_and_keeps_supported_donor():
    corpus, frontend, demands = prepare(source(donor='box.put_other("a",9)\nbox.put("a",1)'))
    result = diagnose(corpus, frontend, demands)
    assert result['counts'] == {'supported_closed_donor': 1, 'call_receiver_or_control_unknown': 2}
    assert all(e['field'] == 'items' for row in result['calls'] for e in row['write_effects'])
    assert diagnose(corpus, frontend, []) == dict(status='no_indexed_demand', calls=[], counts={})


def test_unbound_payload_is_distinguished_from_a_closed_source_action():
    corpus, frontend, demands = prepare(source(donor='box.put("a",external_value)'))
    result = diagnose(corpus, frontend, demands)
    assert result['counts'] == {'missing_literal_dependency': 1, 'call_receiver_or_control_unknown': 2}
    assert all(row['bank_entries'] == 0 for row in result['calls'])


def test_changed_imported_analyzer_cannot_silently_reinterpret_frozen_search():
    current = [dict(path='/source/analyzer.py', sha256='new')]
    with pytest.raises(ValueError, match='differs'):
        verify_census_seals(current, {'/source/analyzer.py': 'old'})
    verify_census_seals(current, {'/source/analyzer.py': 'new'})
