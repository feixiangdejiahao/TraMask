"""Small, explicitly adapted P2 witness constructors; no issue understanding.

Run: python3 src/constructive_p2.py OUTPUT_DIRECTORY
The shared motif manifest supplies the oracle for two different API adapters.
The Koota adapter constructs a current-state fresh-query comparison separately.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path


def motifs():
    return [
        {"id": f"{'shared' if shared else 'disjoint'}-{shape}-{seed}",
         "shared": shared, "shape": shape, "seed": seed}
        for shared, shape, seed in itertools.product(
            (False, True), ("flat", "nested"), (0, 2))
    ]


GO_PREFIX = r'''package tengo_test

import (
    "encoding/json"
    "testing"
    "github.com/d5/tengo/v2"
)

func p2Run(t *testing.T, src string) *tengo.Compiled {
    t.Helper()
    c, err := tengo.NewScript([]byte(src)).Run()
    if err != nil { t.Fatal(err) }
    return c
}
func p2Access(t *testing.T, c *tengo.Compiled, nested bool) (tengo.Object, tengo.Object) {
    t.Helper()
    a := c.Get("data").Object().(*tengo.Array)
    if nested { return a.Value[0], a.Value[1].(*tengo.Map).Value["read"] }
    return a.Value[0], a.Value[1]
}
func p2Call(t *testing.T, f tengo.Object) int64 {
    t.Helper()
    r, err := f.Call()
    if err != nil { t.Fatal(err) }
    n, ok := r.(*tengo.Int)
    if !ok { t.Fatalf("expected Int, got %T", r) }
    return n.Value
}
func TestP2Alias(t *testing.T) {
'''


def tengo(motif_list):
    blocks = [GO_PREFIX]
    for m, operation in itertools.product(motif_list, ("identity", "transfer", "clone")):
        nested = m["shape"] == "nested"
        capture = "n" if m["shared"] else "other"
        container = '[write, {"read": read}]' if nested else '[write, read]'
        program = ("mk := func() {\n n := 0\n other := 0\n"
                   " write := func() { n++; return n }\n"
                   f" read := func() {{ return {capture} }}\n"
                   f" return {container}\n}}\ndata := mk()\n")
        # Tengo rejects an unused local only in some versions; both variables
        # are referenced by the maker to keep the shape constant across motifs.
        program = program.replace(" other := 0\n", " other := 0\n other = other\n")
        seed = m["seed"]
        source_before = seed if m["shared"] else 0
        expected_reader = seed + 1 if m["shared"] else 0
        expected_source = expected_reader if operation == "identity" else source_before
        transform = {
            "identity": "dst := src",
            "transfer": 'dst := p2Run(t, code)\n        if err := dst.Set("data", src.Get("data").Object()); err != nil { t.Fatal(err) }',
            "clone": "dst := src.Clone()",
        }[operation]
        blocks.append(f'''
    t.Run("{m['id']}-{operation}", func(t *testing.T) {{
        const code = `{program}`
        src := p2Run(t, code)
        sw, sr := p2Access(t, src, {str(nested).lower()})
        for i := 0; i < {seed}; i++ {{ p2Call(t, sw) }}
        if before := p2Call(t, sr); before != {source_before} {{ t.Fatalf("source motif invalid: %d", before) }}
        {transform}
        dw, dr := p2Access(t, dst, {str(nested).lower()})
        initial := p2Call(t, dr)
        written := p2Call(t, dw)
        read := p2Call(t, dr)
        sourceRead := p2Call(t, sr)
        got := []int64{{initial, written, read, sourceRead}}
        want := []int64{{{source_before}, {seed + 1}, {expected_reader}, {expected_source}}}
        equal := true
        for i := range got {{ if got[i] != want[i] {{ equal = false }} }}
        rec, _ := json.Marshal(map[string]interface{{}}{{"case": t.Name(), "got": got, "want": want, "pass": equal}})
        t.Logf("P2_RESULT %s", rec)
        if !equal {{ t.Errorf("[initial, written, crossRead, sourceRead] = %v, want %v", got, want) }}
    }})
''')
    blocks.append("}\n")
    return "".join(blocks)


def superjson(motif_list):
    return '''import { expect, test } from 'vitest';
import SuperJSON from './index.js';

const motifs = ''' + json.dumps(motif_list) + ''';
for (const motif of motifs) for (const mode of ['default', 'frames']) {
  test(`P2 alias ${motif.id} ${mode}`, () => {
    const sj = mode === 'default' ? new SuperJSON() : new SuperJSON({errorStack: {mode: 'frames'}});
    sj.allowErrorProps('stackFrames');
    const a = new Error(String(motif.seed));
    a.stack = `Error: ${motif.seed}\\n  at p2 (example.js:1:1)`;
    const b = motif.shared ? a : new Error(String(motif.seed));
    // Keep accessor wrappers distinct even when their mutable cells alias.
    // This matches the distinct-closure/shared-capture motif in Tengo.
    const left = {cell: a};
    const right = {cell: b};
    const source: any = motif.shape === 'flat' ? [left, right] : [left, {read: right}];
    const writer = (x: any): Error => x[0].cell;
    const reader = (x: any): Error => motif.shape === 'flat' ? x[1].cell : x[1].read.cell;
    const dest: any = sj.deserialize(sj.serialize(source));
    const initial = reader(dest).message;
    writer(dest).message = String(motif.seed + 1);
    const got = [initial, writer(dest).message, reader(dest).message, reader(source).message];
    const want = [String(motif.seed), String(motif.seed + 1),
      String(motif.seed + (motif.shared ? 1 : 0)), String(motif.seed)];
    console.log('P2_RESULT ' + JSON.stringify({case: motif.id + '-' + mode, got, want,
      pass: JSON.stringify(got) === JSON.stringify(want)}));
    expect(got).toEqual(want);
    expect(writer(dest) === reader(dest)).toBe(motif.shared);
    expect(writer(dest)).not.toBe(writer(source));
    expect(dest[0]).not.toBe(motif.shape === 'flat' ? dest[1] : dest[1].read);
    // This construction observes alias and isolation only. The shape of the
    // restored stack is a different contract and is not used as its oracle.
  });
}
'''


def koota():
    # Exhaust all histories of one or two operations in this small declared
    # domain. Oracle does not contain expected predicate membership.
    ops = ["set-low", "set-high", "remove", "add-low", "add-high"]
    histories = [[op] for op in ops] + [list(pair) for pair in itertools.product(ops, repeat=2)]
    return '''import { expect, test } from 'vitest';
import { createPredicate, createWorld, Not, trait } from '../src';

const histories = ''' + json.dumps(histories) + ''';
for (const history of histories) for (const negate of [false, true]) {
  test(`P2 fresh query ${history.join(',')} negate=${negate}`, () => {
    const Health = trait({value: 0});
    const world = createWorld();
    world.init();
    try {
      const factory = createPredicate([Health], ([h]) => h.value > 0);
      const stable = factory();
      const entity = world.spawn(Health({value: 1}));
      world.spawn(Health({value: -1}));
      const query = (p: any) => world.query(negate ? Not(p) : p).slice().sort((a, b) => a - b);
      const warm = query(stable);
      let present = true;
      const comparisons: any[] = [];
      for (const op of history) {
        if (op === 'remove') { if (present) entity.remove(Health); present = false; }
        else if (op.startsWith('set')) {
          if (!present) { entity.add(Health({value: 0})); present = true; }
          entity.set(Health, {value: op.endsWith('high') ? 1 : -1});
        } else {
          if (present) entity.remove(Health);
          entity.add(Health({value: op.endsWith('high') ? 1 : -1})); present = true;
        }
        const retained = query(stable);
        const fresh = query(factory());
        comparisons.push({op, retained, fresh});
      }
      const pass = comparisons.every(c => JSON.stringify(c.retained) === JSON.stringify(c.fresh));
      console.log('P2_RESULT ' + JSON.stringify({case: history.join(',') + '-' + negate, warm, comparisons, pass}));
      expect(pass).toBe(true);
    } finally { world.destroy(); }
  });
}
'''


def presence():
    result = ['package tengo_test\nimport ("encoding/json"; "testing"; "github.com/d5/tengo/v2")\nfunc TestP2Presence(t *testing.T) {\n']
    for shape in ("array", "map"):
        for state in ("absent", "undefined", "zero"):
            value = "undefined" if state == "undefined" else "0"
            if shape == "array":
                pattern = "[x = fallback()]"
                source = "[]" if state == "absent" else f"[{value}]"
            else:
                pattern = "{k: x = fallback()}"
                source = "{}" if state == "absent" else f"{{k: {value}}}"
            expected = "7" if state == "absent" else value
            calls = 1 if state == "absent" else 0
            result.append(f'''
  t.Run("{shape}-{state}", func(t *testing.T) {{
    c, err := tengo.NewScript([]byte(`hits := 0
fallback := func() {{ hits++; return 7 }}
{pattern} := {source}
`)).Run()
    if err != nil {{ t.Fatal(err) }}
    got := c.Get("x").Object().String()
    hits := c.Get("hits").Int()
    pass := got == "{expected}" && hits == {calls}
    rec, _ := json.Marshal(map[string]interface{{}}{{"case": t.Name(), "value": got, "hits": hits, "want_value": "{expected}", "want_hits": {calls}, "pass": pass}})
    t.Logf("P2_RESULT %s", rec)
    if !pass {{ t.Errorf("value=%s hits=%d, want value={expected} hits={calls}", got, hits) }}
  }})
''')
    result.append("}\n")
    return "".join(result)


def main():
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    items = motifs()
    (out / "motifs.json").write_text(json.dumps(items, indent=2) + "\n")
    (out / "p2_alias_test.go").write_text(tengo(items))
    (out / "p2-alias.test.ts").write_text(superjson(items))
    (out / "p2-fresh.test.ts").write_text(koota())
    (out / "p2_presence_test.go").write_text(presence())
    print(json.dumps({"directory": str(out), "motifs": len(items),
                      "tengo_cases": len(items) * 3, "superjson_cases": len(items) * 2,
                      "koota_cases": 60, "presence_cases": 6}))


if __name__ == "__main__":
    main()
