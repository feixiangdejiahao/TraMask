import pytest

from relation_search.oracle_constant_mask import collect


@pytest.mark.parametrize('language,code,operand',[
    ('go','func Test(t *T) { want := "old"; if got != want { t.Errorf("%s", want) } }','want'),
    ('python','def test():\n    want = "old"\n    assert got == want, want\n','want'),
    ('typescript','it("x",()=>{ const want = "old"; expect(got).toEqual(want); });','want'),
])
def test_only_oracle_constant_definitions_are_masked(language,code,operand):
    begin=code.index(operand,code.index('got'))
    result=collect(code,language,[(begin,begin+len(operand))])
    assert len(result)==1
    assert code.encode()[result[0]['start']:result[0]['end']]==b'"old"'


def test_shared_input_constant_and_observed_operand_stay_visible():
    for code in [
        'def test():\n    want = "old"\n    got = parse(want)\n    assert got == want\n',
        'def test():\n    want = "old"\n    assert got == want\n    assert want == 3\n',
    ]:
        begin=code.index('want',code.index('assert got'))
        assert collect(code,'python',[(begin,begin+4)])==[]


def test_multiple_definitions_and_effectful_oracle_values_are_not_redacted():
    for code in [
        'def test():\n    want = "old"\n    want = "new"\n    assert got == want\n',
        'def test():\n    want = make_expected()\n    assert got == want\n',
    ]:
        begin=code.rindex('want')
        assert collect(code,'python',[(begin,begin+4)])==[]
