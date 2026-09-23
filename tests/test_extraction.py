import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from extract_tests import extract

def test_python_decorator_and_oracle():
 rows=extract('test_sample.py','''import pytest
@pytest.mark.parametrize("value", [0, 2])
def test_boundary(value, tmp_path):
    result = parse(value)
    assert result == value + 1
''')
 assert len(rows)==1
 assert rows[0]['start_line']==2
 assert 'parse' in rows[0]['calls']
 assert rows[0]['parameters']==['value','tmp_path']
 assert rows[0]['assertions']==['assert result == value + 1']

def test_go_function_not_helper():
 rows=extract('thing_test.go','''package example
func helper() {}
func TestCall(t *testing.T) { x := clone.Call(2); require.Equal(t, 3, x) }
''')
 assert [r['name'] for r in rows]==['TestCall']
 assert 'clone.Call' in rows[0]['calls']
 assert rows[0]['assertions']

def test_ts_nested_test_and_no_describe_duplication():
 rows=extract('thing.test.ts', '''describe('schema', () => { test('transform', () => { expect(parse(1)).toEqual(2); }); });''')
 assert len(rows)==1
 assert 'parse' in rows[0]['calls']
 assert rows[0]['assertions']

def test_script_assertion_and_invalid_syntax():
 assert extract('trajectory/step.py','x = parse(1)\nassert x == 2','trajectory')[0]['name']=='<script>'
 assert extract('test_bad.py','def test_(:')==[]
