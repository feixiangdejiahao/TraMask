"""Replay unchanged direct-generation proposals with source metadata added.

Original code bytes and complete raw generation/review receipts remain strict
dependencies. This bridge seals a new execution closure. It does not claim to
execute under either original process's loaded-module inventory.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import direct_generation_provenance as provenance
from relation_search.checkpoint import read
from relational_gap import provider as provider_adapter
from scripts import run_contract_gap_generation_search as original
from scripts import run_atomic_contract_gap_generation_search as atomic
from scripts import run_test_admission as admission
from scripts.run_contract_repair_search import frozen, verify, write

VERSION = 'direct-generation-provenance-native-replay.v1'
SUPPORTED = {original.VERSION: original, atomic.VERSION: atomic}
POLICY = dict(version=VERSION,
    change='Add source_provenance only. Preserve every candidate ID, body edit, import, test binding, rank and original decision.',
    origin='Require complete original generation and semantic summaries. Recompute all original decoding, decisions, ordering and accounting from their raw receipts.',
    closure='Verify every original algorithm byte and original entrypoint association; separately seal and verify this new loaded-module closure.',
    native='Reuse original complete-test transport, original source controls and first admitted failure plus one repeat. Preserve earlier failure directories.',
    provider='No provider dispatch or new semantic judgment in this bridge.')


def _module(protocol):
    if protocol.get('version') not in SUPPORTED:
        raise ValueError('Unsupported original direct-generation protocol')
    return SUPPORTED[protocol['version']]


def _old_algorithm(protocol):
    """Validate old bytes/entrypoint bindings, without a false old-closure claim."""
    module = _module(protocol)
    entrypoints = protocol.get('algorithm_entrypoints', {})
    expected = dict(driver=frozen(module.__file__), constructor=frozen(module.relation.__file__),
        semantic_reviewer=frozen(original.review.__file__), native_adapter=frozen(original.__file__),
        provider_adapter=frozen(provider_adapter.__file__))
    if entrypoints != expected:
        raise ValueError('Original executed entrypoint association differs')
    recorded = {(r['path'], r['sha256']) for r in protocol['algorithm'].values()}
    if any((r['path'], r['sha256']) not in recorded for r in entrypoints.values()):
        raise ValueError('Original executed entrypoint absent from original seal')
    admission.verify_seal(protocol['algorithm'])
    admission.verify_seal(entrypoints)


def _old_engine(protocol):
    module = _module(protocol)
    old = dict(vars(module)) if module is original else module._engine()
    namespace = dict(old, _verify_algorithm=_old_algorithm)
    for name, function in old.items():
        if name == '_verify_algorithm':
            continue
        if isinstance(function, FunctionType) and (
                function.__globals__ is old or function.__globals__ is vars(original)
                or function.__globals__ is vars(module)):
            # R22's custom functions use its module globals and custom _engine.
            # Keep those exact functions; its cloned R18 functions use old.
            if module is atomic and function.__globals__ is vars(atomic):
                continue
            bound = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = bound
    return namespace


def verify_origin(root):
    root = Path(root)
    protocol = read(root/'prepared.json')
    if read(root/'seal.json') != frozen(root/'prepared.json'):
        raise ValueError('Original native protocol seal differs')
    _old_algorithm(protocol)
    engine = _old_engine(protocol)
    engine['_verify_protocol'](protocol)
    # Both functions validate raw completions, exact decoded programs, all
    # refusals/unknowns and measured/reserved costs. Neither dispatches.
    generation = engine['_verify_generation_origin'](protocol)
    semantic = engine['_verified_semantic'](root, protocol)
    for case in protocol['cases']:
        engine['_verify_case_inputs'](case)
    return protocol, generation, semantic


def _augmented(case, entry):
    corpus = read(case['inputs']['corpus.json']['path'])
    candidate = read(entry['program']['path'])
    payload = json.loads(read(entry['request']['path'])['prompt']) if entry['request'] else None
    return provenance.attach(corpus, candidate, payload)


def prior_execution_boundary(root, protocol):
    """Inspect an interrupted emission without executing or changing it."""
    forbidden = [p for pattern in ('**/native_outcome.json', '**/executed/runs.json',
                                    '**/outcome.json', '**/emitted/group_*/manifest.json')
                 for p in root.glob(pattern)]
    if forbidden:
        raise ValueError('Existing subject execution/emission needs a separate continuation policy')
    by_directory = {root/'cases'/case['case']/f"candidate_{entry['rank']:04d}": entry
                    for case in protocol['cases'] for entry in case['candidates']}
    interrupted = []
    for directory, entry in by_directory.items():
        for phase in ('initial', 'confirmation'):
            pending = directory/phase
            if not pending.exists():
                continue
            native = pending/'native'
            stage = native/'emitted/stage.json'
            programs = native/'prepared/candidates.json'
            if not stage.exists() or not programs.exists():
                raise ValueError('Unrecognized prior native interruption')
            record = read(stage); candidate = read(entry['program']['path'])
            if (record.get('stage') != 'emit' or read(programs) != dict(candidates=[candidate])
                    or candidate.get('source_provenance', candidate.get('provenance', candidate.get('source_evidence')))):
                raise ValueError('Prior interruption does not match missing source metadata')
            interrupted.append(dict(program=entry['program'], phase=phase, stage=frozen(stage),
                prepared_candidate=frozen(programs),
                classification='source_provenance_precondition_unsatisfied_before_emission',
                inferred_exception='ValueError: Search candidate requires source provenance',
                exception_basis='Static branch predicate in the sealed emitter plus its pending input and stage; no traceback artifact is asserted.',
                files=[frozen(p) for p in sorted(pending.rglob('*')) if p.is_file()]))
    return dict(version='pre-emission-source-metadata-boundary.v1',
        original_prepared=frozen(root/'prepared.json'),
        emitter_source=frozen(original.admission.ROOT/'scripts/execute_relation_search.py'),
        recorded_subject_executions=0, interrupted=interrupted,
        limitations='Absence of execution artifacts and the pre-emission guard establish this recorded boundary. This report does not invent a missing runtime traceback.')


def _verify_protocol(protocol):
    if protocol.get('version') != VERSION or protocol.get('policy') != POLICY:
        raise ValueError('Unsupported provenance bridge')
    if protocol.get('phase') != 'semantic_native':
        raise ValueError('Bridge is native-only')
    for receipt in protocol['origin'].values():
        verify(receipt)
    if protocol['origin']['semantic_summary_copy']['sha256'] != protocol['origin']['semantic_summary']['sha256']:
        raise ValueError('Inherited semantic summary bytes differ')
    origin = read(protocol['origin']['prepared']['path'])
    inherited = set(origin)-{'version', 'algorithm', 'algorithm_entrypoints', 'cases', 'policy'}
    if any(protocol.get(key) != origin[key] for key in inherited):
        raise ValueError('Bridge changed original policy or execution budget')
    if len(protocol['cases']) != len(origin['cases']):
        raise ValueError('Bridge omitted an original case')
    for case, old in zip(protocol['cases'], origin['cases']):
        if {k:v for k,v in case.items() if k != 'candidates'} != {k:v for k,v in old.items() if k != 'candidates'}:
            raise ValueError('Bridge changed original case inputs')
        if len(case['candidates']) != len(old['candidates']):
            raise ValueError('Bridge omitted an original proposal')
        for entry, previous in zip(case['candidates'], old['candidates']):
            if entry.get('original_program') != previous['program']:
                raise ValueError('Bridge program lost original proposal receipt')
            if {k:v for k,v in entry.items() if k not in {'program','original_program'}} != {
                    k:v for k,v in previous.items() if k != 'program'}:
                raise ValueError('Bridge changed proposal ordering or review')
            verify(entry['program']); verify(previous['program'])
            if read(entry['program']['path']) != _augmented(old, previous):
                raise ValueError('Bridge added more than verified source metadata')


def _verify_algorithm(protocol):
    admission._preload_local_imports(sys.modules[__name__])
    if protocol['algorithm_entrypoints'] != _entrypoints():
        raise ValueError('Bridge executed entrypoints differ')
    original._verify_nested_receipts(protocol['algorithm_entrypoints'])
    recorded = {(r['path'],r['sha256']) for r in protocol['algorithm'].values()}
    if any((r['path'],r['sha256']) not in recorded for r in protocol['algorithm_entrypoints'].values()):
        raise ValueError('Bridge entrypoint absent from new closure')
    admission._verify_sources(protocol['algorithm_entrypoints'], protocol['algorithm'])
    _old_algorithm(read(protocol['origin']['prepared']['path']))


def _verify_generation_origin(protocol):
    return verify_origin(Path(protocol['origin']['prepared']['path']).parent)[1]


def _verified_semantic(root, protocol):
    if frozen(root/'semantic_summary.json') != protocol['origin']['semantic_summary_copy']:
        raise ValueError('Native summary does not reference the exact inherited semantic summary')
    return verify_origin(Path(protocol['origin']['prepared']['path']).parent)[2]


def _entrypoints():
    return dict(driver=frozen(__file__), constructor=frozen(provenance.__file__),
        semantic_reviewer=frozen(original.review.__file__), native_adapter=frozen(original.__file__),
        provider_adapter=frozen(provider_adapter.__file__))


def _engine():
    namespace = dict(vars(original))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
        _verify_protocol=_verify_protocol, _verify_algorithm=_verify_algorithm,
        _verify_generation_origin=_verify_generation_origin, _verified_semantic=_verified_semantic,
        one_run=one_run)
    namespace.update(overrides)
    for name, function in vars(original).items():
        if name not in overrides and isinstance(function, FunctionType) and function.__module__ == original.__name__:
            bound = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            bound.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = bound
    return namespace


one_run = original.one_run


def prepare(args):
    source = args.input.resolve()
    old, generation, semantic = verify_origin(source)
    if old['trial_denominator'] != 17:
        raise ValueError('Full seventeen-trial cohort required')
    prior_boundary = prior_execution_boundary(source, old)
    args.output.mkdir(parents=True, exist_ok=False)
    write(args.output/'prior_execution_boundary.json', prior_boundary)
    # This is an explicitly inherited summary, not a new model judgment. Keep
    # its original bytes and its original prepared/result references intact.
    (args.output/'semantic_summary.json').write_bytes((source/'semantic_summary.json').read_bytes())
    cases = []
    for case in old['cases']:
        entries = []
        for entry in case['candidates']:
            target = args.output/'cases'/case['case']/f"candidate_{entry['rank']:04d}"/'program.json'
            write(target, _augmented(case, entry))
            entries.append(dict(entry, original_program=entry['program'], program=frozen(target)))
        cases.append(dict(case, candidates=entries))
    admission._preload_local_imports(sys.modules[__name__])
    protocol = dict(copy.deepcopy(old), version=VERSION, policy=POLICY, cases=cases,
        origin=dict(prepared=frozen(source/'prepared.json'), seal=frozen(source/'seal.json'),
                    semantic_summary=frozen(source/'semantic_summary.json'),
                    semantic_summary_seal=frozen(source/'semantic_summary_seal.json'),
                    semantic_summary_copy=frozen(args.output/'semantic_summary.json'),
                    prior_execution_boundary=frozen(args.output/'prior_execution_boundary.json')),
        algorithm=admission._loaded_sources(), algorithm_entrypoints=_entrypoints())
    _verify_protocol(protocol); _verify_algorithm(protocol)
    write(args.output/'prepared.json', protocol); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(prepared=frozen(args.output/'prepared.json'), trials=len(cases),
        proposals=sum(len(c['candidates']) for c in cases), admitted=len(semantic['admitted']),
        inherited_generation_calls=generation['provider_calls'], inherited_review_calls=semantic['provider_calls'],
        new_provider_calls=0, native_executions=0)


def run(args):
    return _engine()['run'](args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare', 'run'])
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.stage == 'prepare' and args.output is None:
        parser.error('prepare requires --output')
    print(json.dumps(prepare(args) if args.stage == 'prepare' else run(args)))
