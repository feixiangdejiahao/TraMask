"""Independent examples for the observation-frontier abstraction."""
from anchor_retrieval.frontier import order_test, rank_frontier
from anchor_retrieval.index import Index
from anchor_retrieval.retrieve import make_anchors, rank
from anchor_retrieval.syntax import Source


def analyze(production, tests, language='python'):
    filename, testname = {'python': ('calc.py', 'test_calc.py'),
                          'go': ('calc.go', 'calc_test.go'),
                          'typescript': ('calc.ts', 'calc.test.ts')}[language]
    patch = f'+++ b/{filename}\n@@ -0,0 +1,{len(production.splitlines())} @@\n'
    patch += '\n'.join('+' + s for s in production.splitlines())
    index = Index([Source(filename, production, language), Source(testname, tests, language)], patch)
    rows, _ = make_anchors(index)
    return rows, patch


INVOICE = '''class Invoice:
    def __init__(self, cost, tax):
        self.cost = cost
        self.tax = tax
        self.total = self.cost + self.tax
'''


def test_combined_observation_dominates_each_component():
    rows, _ = analyze(INVOICE, '''from calc import Invoice
def test_billing():
    bill = Invoice(30, 4)
    assert bill.cost == 30
    assert bill.tax == 4
    assert bill.total == 34
''')
    ordered = order_test(rows)
    assert ordered[0]['frontier']['observed_expression'] == 'bill.total'
    assert ordered[0]['frontier']['layer'] == 0
    assert all(r['frontier']['layer'] > 0 for r in ordered[1:])


def test_parameter_oracle_distinguishes_more_results_on_same_front():
    rows, _ = analyze('''class Reading:
    def __init__(self, code, value):
        self.code = code
        self.value = value
def measure(x):
    return Reading(17, x)
''', '''import pytest
from calc import measure
@pytest.mark.parametrize(('raw', 'expected'), [(2, 2), (4, 4), (8, 8)])
def test_range(raw, expected):
    reading = measure(raw)
    assert reading.code == 17
    assert reading.value == expected
''')
    ordered = order_test(rows)
    assert ordered[0]['frontier']['observed_expression'] == 'reading.value'
    assert ordered[0]['frontier']['expected_diversity'] == 3
    assert ordered[1]['frontier']['expected_diversity'] == 1
    assert order_test(rows, use_expectation=False)[0]['line'] < ordered[0]['line']


def test_later_state_observation_does_not_subsume_an_earlier_one():
    rows, _ = analyze('''class Meter:
    def __init__(self): self.count = 0
    def read(self): return self.count
    def advance(self): self.count += 1
''', '''from calc import Meter
def test_steps():
    meter = Meter()
    before = meter.read()
    assert before == 0
    meter.advance()
    after = meter.read()
    assert after == 1
''')
    order_test(rows)
    assert [r['frontier']['layer'] for r in rows] == [0, 0]
    before, after = [set(r['frontier']['footprint']) for r in rows]
    assert not before <= after and not after <= before


def test_consumption_of_configuration_dominates_configuration_inspection():
    rows, _ = analyze('''export function configure(size: number) { return { size }; }
export function execute(config: {size: number}, value: number) { return config.size * value; }
''', '''import { configure, execute } from './calc';
test('configuration is consumed', () => {
  const config = configure(3);
  expect(config.size).toBe(3);
  expect(execute(config, 7)).toBe(21);
});
''', 'typescript')
    ordered = order_test(rows)
    assert ordered[0]['frontier']['observed_expression'] == 'execute(config, 7)'
    assert set(rows[0]['frontier']['footprint']) < set(rows[1]['frontier']['footprint'])


def test_constant_capability_is_not_a_value_dependency():
    rows, _ = analyze('''package calc
type Worker struct { Amount int }
func New() *Worker { return &Worker{Amount: 9} }
func (w *Worker) Ready() bool { return true }
func (w *Worker) Run(x int) int { return w.Amount + x }
''', '''package calc
import "github.com/stretchr/testify/require"
func TestWorker(t *testing.T) {
  w := New()
  require.True(t, w.Ready())
  require.Equal(t, 14, w.Run(5))
}
''', 'go')
    ordered = order_test(rows)
    assert ordered[0]['frontier']['observed_expression'] == 'w.Run(5)'
    assert rows[0]['frontier']['constant_return_calls'] == ['w.Ready()']


def test_alpha_renaming_and_unrelated_setup_preserve_the_frontier():
    template = '''from calc import Invoice
def TEST():
    OBJECT = Invoice(30, 4)
    NOISE
    assert OBJECT.cost == 30
    assert OBJECT.tax == 4
    assert OBJECT.total == 34
'''
    for test, obj, noise in [('test_cost', 'bill', 'noise = 100'),
                              ('test_other', 'record', 'noise = str(99)')]:
        rows, _ = analyze(INVOICE, template.replace('TEST', test).replace('OBJECT', obj).replace('NOISE', noise))
        selected = order_test(rows)[0]
        assert selected['frontier']['observed_expression'] == obj + '.total'


def test_frontier_is_independent_of_assertion_order():
    for assertions in [
        ['assert bill.cost == 30', 'assert bill.tax == 4', 'assert bill.total == 34'],
        ['assert bill.total == 34', 'assert bill.tax == 4', 'assert bill.cost == 30'],
    ]:
        rows, _ = analyze(INVOICE, 'from calc import Invoice\ndef test_example():\n    bill = Invoice(30, 4)\n    '
                          + '\n    '.join(assertions) + '\n')
        assert order_test(rows)[0]['frontier']['observed_expression'] == 'bill.total'


def test_budget_rounds_do_not_let_one_large_test_consume_all_places():
    rows, patch = analyze(INVOICE, '''from calc import Invoice
def test_first():
    bill = Invoice(30, 4)
    assert bill.cost == 30
    assert bill.tax == 4
    assert bill.total == 34
def test_second():
    bill = Invoice(20, 5)
    assert bill.total == 25
''')
    baseline = rank(rows, 'legacy_keywords', patch)
    ranked = rank_frontier(rows, baseline)
    assert len({r['test_id'] for r in ranked[:2]}) == 2
    assert ranked[0]['frontier']['observed_expression'] == 'bill.total'
