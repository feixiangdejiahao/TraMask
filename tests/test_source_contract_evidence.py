from relation_search.source_contract_evidence import collect


def test_resolved_types_and_adjacent_api_docs_are_recovered_without_body():
    api="import type { Container } from './types';\n/** Returns a collection, not a relation. */\nexport function wrap(x: number): Container { return secretImplementation(x); }\n"
    header='function wrap(x: number): Container '
    start=api.index(header)
    corpus=dict(language='typescript',sources={'api.ts':dict(code=api),
        'types.ts':dict(code='export interface Container { values: string[]; }\n')})
    analysis=dict(sources={'S0':dict(path='api.ts',start_byte=start,end_byte=start+len(header),code=header)},
        boundaries=[dict(declaration_header=dict(source='S0',start=0,end=len(header)))])
    out=collect(corpus,analysis)
    assert {r['kind'] for r in out['records']}=={'api_documentation','type_declaration'}
    assert 'collection' in str(out)
    assert 'values: string[]' in str(out)
    assert 'secretImplementation' not in str(out)


def test_source_span_mismatch_never_retrieves_by_similar_name():
    corpus=dict(language='python',sources={'api.py':dict(code='def f(x):\n    """Returns x."""\n    return x\n')})
    analysis=dict(sources={'S0':dict(path='api.py',start_byte=0,end_byte=9,code='def g(x):')},
        boundaries=[dict(declaration_header=dict(source='S0',start=0,end=9))])
    out=collect(corpus,analysis)
    assert not out['records']
    assert out['unknowns'][0]['reason']=='declaration_source_span_mismatch'
