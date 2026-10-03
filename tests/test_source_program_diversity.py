from anchor_retrieval.syntax import Source
from relational_gap.frontend import extract_frontend,to_emitter_corpus
from relation_search.source_program_diversity import identity,diversify


def sample():
    a=Source('a_test.go','package sample\nimport "testing"\nfunc TestOne(t *testing.T) { if 1 != 1 { t.Fatal("bad") } }\n','go')
    b=Source('b_test.go','package sample\nimport "testing"\nfunc TestTwo(t *testing.T) { if 1 != 1 { t.Fatal("bad") } }\n','go')
    c=Source('other/c_test.go','package sample\nimport "testing"\nfunc TestThree(t *testing.T) { if 1 != 1 { t.Fatal("bad") } }\n','go')
    corpus=to_emitter_corpus(extract_frontend([a,b,c]));rows=[]
    for index,base in enumerate(corpus['tests']):rows.append(dict(id=str(index),base_test_id=base,edits=[],imports=[]))
    return corpus,rows


def test_go_test_names_can_share_allocation_group_but_package_scope_cannot():
    corpus,rows=sample()
    by_path={corpus['tests'][row['base_test_id']]['span']['path']:row for row in rows}
    assert identity(corpus,by_path['a_test.go'])==identity(corpus,by_path['b_test.go'])
    assert identity(corpus,by_path['a_test.go'])!=identity(corpus,by_path['other/c_test.go'])


def test_diversification_keeps_every_candidate_after_distinct_first_layer():
    corpus,rows=sample();candidates={row['id']:row for row in rows};ranking=list(candidates)
    out=diversify(corpus,candidates,ranking)
    assert len(out['ranking'])==3
    assert out['unique_syntax_scopes']==2
    assert [row['layer'] for row in out['ranking']]==[0,0,1]
    assert {row['id'] for row in out['ranking']}==set(ranking)
