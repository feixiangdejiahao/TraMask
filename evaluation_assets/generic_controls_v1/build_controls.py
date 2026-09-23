from pathlib import Path
import hashlib, json, itertools
root=Path('/home/jhx/combination_coverage/data/generic_controls_v1')
private=Path('/tmp/cc-generic-evaluator-v1')
cases={
'C01':('python',{
'library.py':'''def canonical(values):
    """Return a sorted copy, preserving duplicates and leaving values unchanged."""
    return sorted(values)
''',
 'test_library.py':'''from library import canonical

def test_order():
    assert canonical([2, 1]) == [1, 2]

def test_duplicates():
    assert canonical([2, 1, 2]) == [1, 2, 2]

def test_copy():
    values = [2, 1]
    canonical(values)
    assert values == [2, 1]
'''}),
'C02':('python',{
'library.py':'''def area(width, height):
    """Return the number of cells in a width by height rectangle of positive integers."""
    if width > 1 and height > 1:
        return width + height + 1
    return width * height
''',
 'test_library.py':'''from library import area

def test_vertical_strip():
    assert area(1, 2) == 2

def test_horizontal_strip():
    assert area(2, 1) == 2

def test_single_cell():
    assert area(1, 1) == 1
'''}),
'C03':('python',{
'library.py':'''def bump_and_read(left, right, amount):
    """Add amount to left[0], then return right[0]. Both lists must be nonempty."""
    left[0] += amount
    return right[0]
''',
 'test_library.py':'''from library import bump_and_read

def test_separate_values():
    left, right = [3], [3]
    assert bump_and_read(left, right, 1) == 3

def test_shared_value():
    values = [3]
    assert bump_and_read(values, values, 1) == 4

def test_mutation_visible():
    left, right = [3], [3]
    bump_and_read(left, right, 2)
    assert left == [5]
'''}),
'C04':('go',{
'library.go':'''package controls

// Recorder retains every submitted item, including duplicates, in submission order.
type Recorder struct { items []string }
func (r *Recorder) Submit(value string) { r.items = append(r.items, value) }
func (r *Recorder) Count() int { return len(r.items) }
func (r *Recorder) Items() []string { return append([]string{}, r.items...) }
''',
 'library_test.go':'''package controls
import ("testing"; "reflect")
func TestOneSubmission(t *testing.T) {
 r := &Recorder{}; r.Submit("a")
 if r.Count() != 1 { t.Fatal(r.Count()) }
}
func TestDistinctSubmissions(t *testing.T) {
 r := &Recorder{}; r.Submit("a"); r.Submit("b")
 if r.Count() != 2 { t.Fatal(r.Count()) }
 if !reflect.DeepEqual(r.Items(), []string{"a", "b"}) { t.Fatal(r.Items()) }
}
'''}),
'C05':('go',{
'library.go':'''package controls

// Counter applies integer operations in invocation order.
type Counter struct { Value int }
func (c *Counter) Add(amount int) { c.Value += amount }
func (c *Counter) Double() { c.Value *= 2 }
''',
 'library_test.go':'''package controls
import "testing"
func TestAdd(t *testing.T) {
 c := &Counter{Value: 2}; c.Add(3)
 if c.Value != 5 { t.Fatal(c.Value) }
}
func TestDouble(t *testing.T) {
 c := &Counter{Value: 2}; c.Double()
 if c.Value != 4 { t.Fatal(c.Value) }
}
func TestZeroAdd(t *testing.T) {
 c := &Counter{Value: 2}; c.Add(0)
 if c.Value != 2 { t.Fatal(c.Value) }
}
'''}),
'C06':('go',{
'library.go':'''package controls
import "errors"

// Quotient divides nonnegative integers using truncation; zero divisor is an error.
func Quotient(numerator, denominator int) (int, error) {
 if denominator == 0 { return 0, errors.New("zero divisor") }
 return numerator / denominator, nil
}
''',
 'library_test.go':'''package controls
import "testing"
func TestFirstQuotient(t *testing.T) {
 got, err := Quotient(12, 3)
 if err != nil || got != 4 { t.Fatal(got, err) }
}
func TestSecondQuotient(t *testing.T) {
 got, err := Quotient(8, 2)
 if err != nil || got != 4 { t.Fatal(got, err) }
}
func TestZeroDivisor(t *testing.T) {
 _, err := Quotient(12, 0)
 if err == nil { t.Fatal("expected error") }
}
'''}),
'C07':('typescript',{
'library.ts':'''/** An ordered queue. take(n) removes and returns up to n front elements. */
export class Queue {
  private values: number[];
  constructor(values: number[]) { this.values = [...values]; }
  peek(): number | undefined { return this.values[0]; }
  remaining(): number[] { return [...this.values]; }
  take(n: number): number[] {
    if (n > 1 && this.values.length > 1) {
      const first = this.values[0];
      const count = Math.min(n, this.values.length);
      this.values.splice(0, count);
      return Array(count).fill(first);
    }
    return this.values.splice(0, n);
  }
}
''',
 'library.test.ts':'''import { strict as assert } from "node:assert";
import { test } from "node:test";
import { Queue } from "./library.ts";
test("one front element", () => {
  const q = new Queue([1, 2]);
  assert.deepEqual(q.take(1), [1]);
  assert.deepEqual(q.remaining(), [2]);
});
test("short queue", () => {
  const q = new Queue([1]);
  assert.deepEqual(q.take(2), [1]);
});
test("same present observation", () => {
  assert.equal(new Queue([1]).peek(), 1);
  assert.equal(new Queue([1, 2]).peek(), 1);
});
'''}),
'C08':('typescript',{
'library.ts':'''/** Count includes duplicates; first preserves input order and is null when empty. */
export function summarize(values: number[]): { count: number, first: number | null } {
  return { count: values.length, first: values[0] ?? null };
}
''',
 'library.test.ts':'''import { strict as assert } from "node:assert";
import { test } from "node:test";
import { summarize } from "./library.ts";
test("count", () => {
  assert.equal(summarize([1, 2]).count, 2);
  assert.equal(summarize([2, 1]).count, 2);
});
test("first", () => {
  assert.equal(summarize([1, 2]).first, 1);
});
test("empty", () => {
  assert.deepEqual(summarize([]), { count: 0, first: null });
});
'''})}
manifest=[]
for cid,(language,files) in cases.items():
 d=root/cid/'repository';d.mkdir(parents=True,exist_ok=True)
 if language=='go':files['go.mod']='module independent.controls/'+cid.lower()+'\n\ngo 1.20\n'
 if language=='typescript':files['package.json']='{"type":"module","scripts":{"test":"node --test library.test.ts"}}\n'
 paths=[]
 for name,source in files.items():
  (d/name).write_text(source);paths.append({'path':name,'sha256':hashlib.sha256(source.encode()).hexdigest()})
 command={'python':['/home/jhx/combination_coverage/.venv/bin/python','-m','pytest','-q'],'go':['go','test','./...'],'typescript':['node','--test','library.test.ts']}[language]
 manifest.append({'id':cid,'language':language,'repository':str(d),'seed_command':command,'files':paths})
(root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
arrays=[list(x) for n in range(4) for x in itertools.product(range(3),repeat=n)]
gold={
'C01':{'rows':[{'args':[x],'expected':sorted(x),'unchanged_input':x} for x in arrays]},
'C02':{'rows':[{'args':[a,b],'expected':a*b} for a,b in itertools.product(range(1,4),repeat=2)]},
'C03':{'rows':[{'left':a,'right':b,'same_object':same,'amount':inc,'expected':a+inc if same else b} for a,b,inc,same in itertools.product(range(3),range(3),[1,2],[False,True]) if not same or a==b]},
'C04':{'rows':[{'submissions':list(x),'count':len(x),'items':list(x)} for n in range(4) for x in itertools.product(['a','b'],repeat=n)]},
'C05':{'rows':[]},
'C06':{'rows':[{'args':[a,b],'expected':a//b if b else None,'error':b==0} for a,b in itertools.product(range(7),range(4))]},
'C07':{'rows':[{'values':x,'n':n,'taken':x[:n],'remaining':x[n:]} for x,n in itertools.product(arrays,range(4))]},
'C08':{'rows':[{'values':x,'expected':{'count':len(x),'first':x[0] if x else None}} for x in arrays]},
}
for initial in [-1,0,1]:
 for n in range(4):
  for ops in itertools.product(['add1','double'],repeat=n):
   value=initial
   for op in ops:value=value+1 if op=='add1' else 2*value
   gold['C05']['rows'].append({'initial':initial,'operations':ops,'expected':value})
for cid in cases:
 gold[cid]['candidate_known_correct']=cid not in ['C02','C07']
 gold[cid]['domain_limited']=True
correct={
'C02':{'library.py':'def area(width, height):\n    """Return the number of cells in a width by height rectangle of positive integers."""\n    return width * height\n'},
'C07':{'library.ts':'''/** An ordered queue. take(n) removes and returns up to n front elements. */
export class Queue {
  private values: number[];
  constructor(values: number[]) { this.values = [...values]; }
  peek(): number | undefined { return this.values[0]; }
  remaining(): number[] { return [...this.values]; }
  take(n: number): number[] { return this.values.splice(0, n); }
}
'''}}
(private/'oracle_table.json').write_text(json.dumps(gold,indent=2)+'\n')
(private/'correct_replacements.json').write_text(json.dumps(correct,indent=2)+'\n')
seal={'manifest_sha256':hashlib.sha256((root/'manifest.json').read_bytes()).hexdigest(),'oracle_table_sha256':hashlib.sha256((private/'oracle_table.json').read_bytes()).hexdigest(),'correct_replacements_sha256':hashlib.sha256((private/'correct_replacements.json').read_bytes()).hexdigest(),'control_count':len(cases),'bounded_rows':{cid:len(v['rows']) for cid,v in gold.items()},'private_location':str(private),'generation_access':'manifest and each repository only; evaluator table/replacements unavailable'}
Path('/home/jhx/combination_coverage/research/generic_controls_v1_seal.json').write_text(json.dumps(seal,indent=2)+'\n')
print(json.dumps(seal,indent=2))
