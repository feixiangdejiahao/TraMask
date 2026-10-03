from relation_search import oracle
from relation_search.prefix_finalization import construct
from tests.test_test_prefix_projection import fixture


def test_python_prefix_releases_its_resource_before_external_leak_check():
    code='''def test_flow():
    item = acquire()
    item.use(2)
    assert item.value > 0
    item.use(9)
    assert item.value == 11
    item.close()
'''
    args=fixture(code,'python','item.use(2)','item.use(3)')
    row=construct(*args)['candidates'][0];result=oracle.preview(args[0],row)
    assert 'item.use(9)' not in result and result.count('item.close()')==1
    class Resource:
        value=0
        closed=False
        def use(self,number):self.value+=number
        def close(self):self.closed=True
    item=Resource();environment={'acquire':lambda:item}
    exec(result,environment);environment['test_flow']()
    assert item.value==3 and item.closed
    assert args[2]['edits'][0] in row['edits']


def test_go_testify_close_statement_is_copied_without_repeating_acquisition():
    code='''package flow
import "github.com/stretchr/testify/require"
func TestFlow(t *testing.T) {
    item, err := acquire()
    require.NoError(t, err)
    use(item, 2)
    require.True(t, ready(item))
    use(item, 8)
    require.True(t, ready(item))
    require.NoError(t, item.Close())
}
'''
    args=fixture(code,'go','use(item, 2)','use(item, 3)')
    result=oracle.preview(args[0],construct(*args)['candidates'][0])
    assert result.count('acquire()')==1 and result.count('item.Close()')==1
    assert 'use(item, 8)' not in result


def test_removed_resource_acquisition_does_not_create_unbound_cleanup():
    code='''import os
def test_flow():
    path = create_path()
    use(2)
    assert ready()
    other = create_path()
    assert other
    os.remove(path)
    os.remove(other)
'''
    args=fixture(code,'python','use(2)','use(3)')
    result=oracle.preview(args[0],construct(*args)['candidates'][0])
    assert 'os.remove(path)' in result and 'os.remove(other)' not in result
    assert 'other = ' not in result


def test_resource_rebinding_in_removed_suffix_refuses_ambiguous_finalizer():
    code='''def test_flow():
    item = acquire()
    use(2)
    assert ready()
    item = acquire()
    assert ready()
    item.close()
'''
    args=fixture(code,'python','use(2)','use(3)')
    result=construct(*args)
    assert result['finalization']['refused_prefixes'][0]['reason']=='resource_rebound_in_removed_suffix'
    assert len(result['candidates'])==1


def test_retained_finalizer_keeps_an_existing_oracle_revision():
    code='''package flow
import "github.com/stretchr/testify/require"
func TestFlow(t *testing.T) {
    item := acquire()
    use(2)
    require.True(t, ready())
    require.NoError(t, item.Close())
}
'''
    corpus,frontend,candidate=fixture(code,'go','use(2)','use(3)')
    before='require.NoError(t, item.Close())';at=code.index(before)
    candidate['edits'].append(dict(span=dict(path='flow_test.go',start_byte=at,end_byte=at+len(before)),
        before=before,after='require.Error(t, item.Close())',role='semantic_expected'))
    row=construct(corpus,frontend,candidate)['candidates'][0]
    assert 'require.Error(t, item.Close())' in oracle.preview(corpus,row)
    assert row['prefix_finalization']['retained'][0]['retained_expected_edits']==1
