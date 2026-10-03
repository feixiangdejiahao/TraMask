from relation_search.seed_frontier import rank


def test_source_priority_is_not_overridden_by_operator_name_or_repeated_seed():
    rows = [dict(id='a',base_test_id='unrelated',source_retrieval_rank=80,content_sha256='a',rank=1),
            dict(id='b',base_test_id='relevant',source_retrieval_rank=1,content_sha256='b',rank=2),
            dict(id='c',base_test_id='relevant',source_retrieval_rank=1,content_sha256='c',rank=3),
            dict(id='d',base_test_id='unknown',source_retrieval_rank=None,content_sha256='d',rank=4)]
    result = rank(rows)
    assert [r['id'] for r in result] == ['b','a','d','c']
    assert [r['rank'] for r in result] == [1,2,3,4]
    assert rows[0]['rank']==1


def test_empty_pool_is_retained_as_empty():
    assert rank([])==[]
