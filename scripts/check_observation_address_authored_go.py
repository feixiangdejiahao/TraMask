"""Native check of the address constructor on one authored, non-benchmark API.

The expected value is explicitly supplied by this fixture's overwrite contract;
it is NOT inferred by the generator. No model or benchmark code is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anchor_retrieval.syntax import Source
from prototypes.observation_address_join import generate
from generic_composition.emitter import emit
from relational_gap.frontend import extract_frontend, to_emitter_corpus

SOURCE = '''package sample
import "testing"
type Store struct { items map[string]int }
func Make() *Store { return &Store{items:map[string]int{"b":0}} }
// Contract of this authored fixture: Put replaces the value of any key.
func(s *Store) Put(k string,v int) { s.items[k]=v }
func(s *Store) Get(k string) int { return s.items[k] }
func TestDonor(t *testing.T) {
 box:=Make()
 box.Put("a",1)
 value:=box.Get("a")
 if value!=1 { t.Fatal("wrong") }
}
func TestTarget(t *testing.T) {
 box:=Make()
 value:=box.Get("b")
 if value!=0 { t.Fatal("wrong") }
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    if output.exists():
        raise ValueError('Use a new output directory; never overwrite receipts')
    output.mkdir(parents=True)
    sources = [ROOT / 'prototypes' / name for name in
               ('observation_address_join.py', 'observation_address_effects.py')]
    sources.append(Path(__file__).resolve())
    seals = {str(path): digest(path) for path in sources}
    frontend = extract_frontend([Source('addresses_test.go', SOURCE, 'go')])
    corpus = to_emitter_corpus(frontend)
    variants = {}
    for mode in ('receiver_only', 'address'):
        result = generate(corpus, frontend, mode=mode)
        choices = [c for c in result['candidates'] if c['base_test_id'].endswith(':TestTarget')]
        if len(choices) != 1:
            raise AssertionError('Expected one generated target in authored fixture')
        emitted = emit(corpus, choices)
        if emitted['unsupported'] or len(emitted['files']) != 1:
            raise AssertionError('Authored fixture must emit one file')
        variants[mode] = (next(iter(emitted['files'].values())), emitted['obligations'][0]['test_name'])
        (output / (mode + '_generation.json')).write_text(json.dumps(result, indent=2) + '\n')
    rows = []
    with tempfile.TemporaryDirectory(prefix='address-go-cache-') as cache:
        environment = dict(os.environ, GOCACHE=cache, GO111MODULE='off', GOPROXY='off', GOTOOLCHAIN='local')
        jobs = [('original', 'original', SOURCE, 'Test(Donor|Target)')]
        for mode, (code, name) in variants.items():
            for oracle in ('retained', 'explicit_new'):
                jobs.append((mode, oracle, code if oracle == 'retained' else
                             code.replace('if value!=0', 'if value!=1'), name))
        for mode, oracle, code, name in jobs:
            for implementation in ('overwrite', 'insert_only_bug'):
                modified = code if implementation == 'overwrite' else code.replace(
                    's.items[k]=v', 'if _, exists:=s.items[k]; !exists { s.items[k]=v }')
                work = output / (mode + '_' + oracle + '_' + implementation)
                work.mkdir()
                program = work / 'addresses_test.go'
                program.write_text(modified)
                t0 = time.monotonic()
                result = subprocess.run(['/usr/bin/go', 'test', '-count=1', '-run', '^(' + name + ')$', '.'],
                    cwd=work, env=environment, text=True, capture_output=True, timeout=60)
                (work / 'stdout.txt').write_text(result.stdout)
                (work / 'stderr.txt').write_text(result.stderr)
                expected_pass = (mode == 'original' or
                    (mode == 'receiver_only' and oracle == 'retained') or
                    (mode == 'address' and oracle == 'retained' and implementation == 'insert_only_bug') or
                    (mode == 'address' and oracle == 'explicit_new' and implementation == 'overwrite'))
                row = dict(mode=mode, oracle=oracle, implementation=implementation,
                    program=str(program), program_sha256=digest(program), exit_code=result.returncode,
                    expected_pass=expected_pass, seconds=time.monotonic()-t0)
                rows.append(row)
                if (result.returncode == 0) != expected_pass or (not expected_pass and 'wrong' not in result.stdout):
                    raise AssertionError(row)
    if seals != {str(path): digest(path) for path in sources}:
        raise AssertionError('Frozen source changed during native checks')
    report = dict(source_seals=seals, source_contract='Put overwrites existing keys',
        oracle_origin='Explicit authored fixture contract, not generator inference',
        benchmark_trials=0, provider_calls=0, authored_native_executions=len(rows), rows=rows,
        interpretation='Demonstrates native code construction and the need for independent oracle adaptation; no benchmark accuracy or novelty claim.')
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({key: result[key] for key in ('benchmark_trials', 'provider_calls', 'authored_native_executions')}))
