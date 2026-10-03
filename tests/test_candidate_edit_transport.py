from relation_search.candidate_edit_transport import test_shape as shape
from relation_search.candidate_edit_transport import go_binding_repair
import pytest


def test_only_outer_test_registration_is_normalized():
    for language,left,right in [('python','def test_a():\n    assert f(1)==2','def test_b():\n    assert f(1)==2'),('go','func TestA(t *testing.T) { check(t, 1) }','func TestB(t *testing.T) { check(t, 1) }'),('typescript',"test('a', () => { expect(f(1)).toBe(2); });","test('b', () => { expect(f(1)).toBe(2); });")]:
        first,last=('test_a','test_b') if language=='python' else ('TestA','TestB') if language=='go' else ('a','b')
        assert shape(left,language,first)==shape(right,language,last)
        assert shape(left,language,first)!=shape(right.replace('1','3'),language,last)


def test_go_local_binding_repair_preserves_one_effectful_initializer():
    source='func TestA(t *testing.T) { value, err := advance(); check(t, err) }'
    result,receipt=go_binding_repair(source,'TestA')
    assert result.count('advance()')==1
    assert '; _ = value' in result
    assert len(receipt['edits'])==1
    assert shape(result,'go','TestA')!=shape(result.replace('_ = value','_ = advance()'),'go','TestA')


def test_go_binding_repair_refuses_unsupported_scope():
    with pytest.raises(ValueError,match='Unsupported unused binding scope'):
        go_binding_repair('func TestA(t *testing.T) { if value := advance(); true { check(t) } }','TestA')
