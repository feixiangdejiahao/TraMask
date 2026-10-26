"""Run counterexamples to unguarded versions of the two proposed properties."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys

from run_constructive_p2 import ORIGINAL, ROOT, record


def main():
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    state = [0]

    def write():
        state[0] += 1
        return state[0]

    def read():
        return state[0]

    source = [write, read]
    dest = copy.deepcopy(source)
    dest[0]()
    assert dest[0] is source[0] and dest[1]() == source[1]() == 1
    (out / "python-function-copy.json").write_text(json.dumps({
        "system": "Python copy.deepcopy",
        "same_function_object": dest[0] is source[0],
        "destination_read": dest[1](), "source_read": source[1](),
        "unguarded_isolation_property": False,
        "classification": "expected by Python contract, not an implementation defect",
    }, indent=2) + "\n")
    code = '''import {expect, test} from 'vitest';
import {createAdded, createPredicate, createWorld, trait} from '../src';
test('P2 boundary: event queries legitimately retain history', () => {
  const H = trait({value: 1});
  const world = createWorld(); world.init();
  try {
    const factory = createPredicate([H], ([h]) => h.value > 0);
    const Added = createAdded();
    const stable = Added(factory());
    const entity = world.spawn(H({value: 1}));
    const first = world.query(stable).slice();
    const retained = world.query(stable).slice();
    const fresh = world.query(Added(factory())).slice();
    console.log('P2_BOUNDARY ' + JSON.stringify({first, retained, fresh}));
    expect(first).toEqual([entity]);
    expect(retained).toEqual([]);
    expect(fresh).toEqual([entity]);
  } finally { world.destroy(); }
});
'''
    (out / "p2-boundary.test.ts").write_text(code)
    cases = {c["id"]: c for c in json.loads((ORIGINAL / "cases.json").read_text())}
    case = cases["T29"]
    source_path = ORIGINAL / "cases/T29/repository"
    cmd = ["docker", "run", "--rm", "--network", "none", "--mount",
           f"type=bind,src={source_path},dst=/input,readonly", "--mount",
           f"type=bind,src={out},dst=/generated,readonly", "--entrypoint", "sh", case["image"], "-c",
           "cp -a /input/. /app/ && cp /generated/p2-boundary.test.ts /app/packages/core/tests/p2-boundary.test.ts && "
           "cd /app/packages/core && ./node_modules/.bin/vitest run tests/p2-boundary.test.ts --maxWorkers 1"]
    record(cmd, ROOT, out / "koota-history")
    print((out / "python-function-copy.json").read_text())


if __name__ == "__main__":
    main()
