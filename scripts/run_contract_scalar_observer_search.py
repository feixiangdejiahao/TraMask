"""Bounded scalar-observer discovery, fresh full-test admission and native checks.

Reuse the direct-generation accounting/receipt machinery in a private function
namespace. The model cannot rewrite bodies: the new constructor alone inserts
captures, two observer reads and equality around an original boundary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import contract_scalar_observer as relation
from relation_search import contract_scalar_observer_review as review
from scripts import run_contract_gap_generation_search as harness
from relational_gap.provider import dispatch

VERSION = 'controlled-contract-scalar-observer-search.v1'

def _prepare(args):
    if read(args.source_cohort/'seal.json') != frozen(args.source_cohort/'prepared.json'):
        raise ValueError('Source cohort seal points to another protocol')
    previous = read(args.source_cohort/'prepared.json')
    sources = {}
    for row in previous.get('items', previous.get('cases', [])):
        if (not isinstance(row.get('case'), str) or row['case'] in {'.', '..'}
                or not re.fullmatch(r'[A-Za-z0-9_.-]+', row['case'])):
            raise ValueError('Invalid trial name')
        if sources.setdefault(row['case'], row['source']) != row['source']:
            raise ValueError('One original source snapshot per trial is required')
    if len(sources) != EXPECTED_TRIALS:
        raise ValueError('Complete seventeen-trial source cohort required')
    deadline = admission._deadline(args.deadline_utc)
    if deadline is None:
        raise ValueError('Deadline required')
    admission._preload_local_imports(sys.modules[__name__])
    algorithm = admission._loaded_sources()
    args.output.mkdir(parents=True, exist_ok=False)
    cases = []
    for case, source_name in sorted(sources.items()):
        source = Path(source_name)
        inputs = {name: frozen(source/name) for name in
                  ('corpus.json', 'frontend.json', 'case.json', 'selection.json', 'issue.md')}
        original = read(source/'corpus.json'); frontend = read(source/'frontend.json')
        corpus, frontend, projection = repository_projection(original, frontend)
        selected = [(identifier, corpus['tests'][identifier]) for identifier in relation.seed_ids(corpus, frontend)]
        identities = {identifier: dict(id=identifier, base_test_id=identifier,
            source_test_ids=[identifier], imports=[], edits=[]) for identifier, _ in selected}
        corpus, enriched = admission._enrich(corpus, frontend, identities,
            source/'corpus.json', args.output, len(cases))
        corpus, frontend, enriched_projection = repository_projection(corpus,
            dict(frontend, sources=corpus['sources']))
        for path, row in original['sources'].items():
            if path in corpus['sources'] and 'complete_file' in row:
                corpus['sources'][path]['complete_file'] = row['complete_file']
        directory = args.output/'cases'/case
        context_dir = directory/'review_projection'
        write(context_dir/'corpus.json', corpus); write(context_dir/'frontend.json', frontend)
        projection.update(original_inputs={key: inputs[key] for key in ('corpus.json', 'frontend.json')},
            enriched_source_sha256=enriched_projection['source_sha256'], source_context=enriched,
            corpus=frozen(context_dir/'corpus.json'), frontend=frozen(context_dir/'frontend.json'))
        write(context_dir/'manifest.json', projection)
        generated = relation.prepare(corpus, frontend, (source/'issue.md').read_text(),
                                     max_prompt_bytes=96000, max_output_tokens=16384)
        target = directory/'generation'
        write(target/'preparation.json', generated)
        if generated['request'] is not None:
            write(target/'request.json', generated['request'])
        cases.append(dict(case=case, source=str(source.resolve()), inputs=inputs,
            generation=frozen(target/'preparation.json'),
            generation_request=frozen(target/'request.json') if generated['request'] else None,
            source_context=enriched, review_projection=frozen(context_dir/'manifest.json'),
            status=generated['status'], candidates=[]))
        print(json.dumps(dict(case=case, status=generated['status'], anchors=len(generated['seeds']),
                              omitted=len(generated['omitted']), prompt_bytes=generated.get('prompt_bytes'))), flush=True)
    record = dict(version=VERSION, phase='generation', policy=relation.POLICY,
        algorithm=algorithm, algorithm_entrypoints=_entrypoints(), cases=cases,
        trial_denominator=len(cases), source_cohort=frozen(args.source_cohort/'prepared.json'),
        source_cohort_use='Original snapshot paths and full trial list only; no old candidates, labels or outcomes.',
        max_candidates_per_trial=relation.MAX_PROPOSALS, deadline_utc=deadline.isoformat(), timeout=180,
        generation_policy=dict(max_calls=17, max_total_tokens=1000000, max_calls_per_trial=1,
            max_prompt_bytes=96000, max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
            ordering='sorted trial names; one non-retriable request per prepared trial'),
        semantic_policy=dict(max_calls=51, max_total_tokens=1500000, max_prompt_bytes=96000,
            max_output_tokens=16384, thinking='enabled', reasoning_effort='high',
            ordering='original proposal ranks round robin over sorted trial names',
            unknown='not executed; not an invalid-test judgment',
            native_outcomes_sent=False, generation_basis_sent=False),
        max_native_executions=4*len(cases),
        stop='First admitted controlled failure then one repeat; stop even if unconfirmed. No audit-driven fallback.',
        comparative_limits=['Fixed first sixteen source hosts; complete original host contexts share a 96000-byte budget with public API declarations.',
            'TypeScript only; model selects a new scalar observer from source-bound objects and argument donors. No new action sequence or input.',
            'Argument captures add one evaluation per chosen donor before the old boundary. Independent review must establish purity, definedness, value identity and all retained assertions.',
            'Complete-test review is independent of generation; execution closures use the existing sealed two-stage generation harness.',
            'No detection or novelty claim follows from source host availability.'],
        provider_calls=0, native_executions=0, evaluation_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    _verify_protocol(record, 'generation'); _verify_algorithm(record)
    write(args.output/'prepared.json', record); write(args.output/'seal.json', frozen(args.output/'prepared.json'))
    return dict(trials=len(cases), requests=sum(bool(case['generation_request']) for case in cases),
                prepared=frozen(args.output/'prepared.json'), provider_calls=0, native_executions=0)



def _engine():
    namespace = dict(vars(harness))
    overrides = dict(__name__=__name__, __file__=__file__, VERSION=VERSION,
                     relation=relation, review=review, dispatch=dispatch)
    namespace.update(overrides)
    for name, function in vars(harness).items():
        if name not in overrides and name != 'prepare' and isinstance(function, FunctionType) and function.__module__ == harness.__name__:
            copied = FunctionType(function.__code__, namespace, name, function.__defaults__, function.__closure__)
            copied.__kwdefaults__ = function.__kwdefaults__
            namespace[name] = copied
    namespace['prepare'] = FunctionType(_prepare.__code__, namespace, 'prepare', _prepare.__defaults__, _prepare.__closure__)
    return namespace


def prepare(args):
    return _engine()['prepare'](args)


def generate(args):
    return _engine()['generate'](args)


def review_all(args):
    return _engine()['review_all'](args)


def run(args):
    return _engine()['run'](args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['prepare','generate','review','run'])
    parser.add_argument('--source-cohort', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--deadline-utc')
    args = parser.parse_args()
    if args.stage == 'prepare' and (args.source_cohort is None or args.output is None or not args.deadline_utc):
        parser.error('prepare requires --source-cohort, --output and --deadline-utc')
    if args.stage != 'prepare' and args.input is None:
        parser.error('generation/review/run requires --input')
    result = {'prepare':prepare,'generate':generate,'review':review_all,'run':run}[args.stage](args)
    print(json.dumps(result))
