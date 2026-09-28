"""Freeze compact program-analysis inputs and relation witness candidates.

Preparation uses only source-visible registered inputs, never evaluation assets.
Later stages consume the frozen bytes and retain their exact provenance.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':')) + '\n').encode()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded(value))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def algorithm_files():
    # This is the preparation dependency boundary. New, unintegrated research
    # modules and provider changes must not silently alter a frozen generation.
    generation = [ROOT/'relational_gap'/f'{name}.py' for name in (
        'inputs', 'frontend', 'history', 'source_dependencies', 'transforms',
        'cells', 'closure', 'identity', 'script_wrappers', 'embedded_relations',
        'structured_ports', 'state_cells', 'atomic_observations', 'scalar_cells',
        'symbolic_strings', 'exception_contexts', 'regex_cells', 'call_contexts',
        'sequence_cells', 'seed_ranking', 'balanced_reachability', 'resource_roots',
        'producer_contexts', 'witness_composition')]
    return sorted([*generation, Path(__file__).resolve(),
                   *ROOT.glob('anchor_retrieval/*.py'), ROOT/'generic_composition/corpus.py',
                   ROOT/'generic_composition/emitter.py', ROOT/'generic_composition/engine.py',
                   ROOT/'generic_composition/edits.py', ROOT/'experimental/local_literal_contexts.py',
                   ROOT/'experimental/finite_inputs.py', ROOT/'experimental/observation_projection.py',
                   ROOT/'experimental/state_regions.py', ROOT/'experimental/semantic_transport/state_contexts.py',
                   ROOT/'experimental/semantic_transport/oracle.py'])


def prepare(args):
    from anchor_retrieval.syntax import diff_lines, units
    from relational_gap.frontend import extract_frontend, to_emitter_corpus
    from relational_gap.inputs import select_sources
    from relational_gap.transforms import enumerate_transforms, TransformBudget
    from relational_gap.cells import generate_cells, merge_candidates, annotate_novelty, CellBudget
    from experimental.finite_inputs import augment_corpus
    from relational_gap.script_wrappers import prepare_script_sources
    from relational_gap.embedded_relations import generate_embedded_relations, EmbeddedRelationBudget
    from relational_gap.state_cells import generate_state_cells, StateBudget
    from relational_gap.atomic_observations import atomize_candidates, AtomicBudget
    from relational_gap.scalar_cells import generate_scalar_cells, ScalarBudget
    from relational_gap.symbolic_strings import generate_symbolic_strings, SymbolicStringBudget
    from relational_gap.exception_contexts import generate_exception_contexts, ExceptionBudget
    from relational_gap.regex_cells import generate_regex_cells, RegexBudget
    from relational_gap.call_contexts import generate_call_contexts, ContextBudget
    from relational_gap.sequence_cells import generate_sequence_cells, SequenceBudget
    from relational_gap.seed_ranking import rank_seeds
    from relational_gap.producer_contexts import generate_producer_contexts, ProducerBudget
    from relational_gap.witness_composition import compose_witnesses, CompositionBudget
    case = next(c for c in json.loads(args.registry.read_text()) if c['id'] == args.case)
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    write(output/'status.json', {'status': 'preparing', 'case': args.case})
    started = time.monotonic()
    source_hashes = {str(path.relative_to(ROOT)): digest(path) for path in algorithm_files()}
    sources, selection = select_sources(case)
    wrapped = prepare_script_sources(sources)
    sources = wrapped['sources']
    selection['script_wrappers'] = wrapped['records']
    patch = Path(case['candidate_patch']).read_text()
    changed = diff_lines(patch)
    symbols = set(selection['changed_symbols'])
    tests = [unit for source in sources for unit in units(source)[0] if unit.test]
    def priority(unit):
        touched = any(unit.node.start_point.row + 1 <= line <= unit.node.end_point.row + 1
                      for line in changed.get(unit.source.path, []))
        tokens = set(re.findall(r'[A-Za-z_]\w*', unit.source.text(unit.node)))
        return (not touched, unit.source.origin != 'trajectory', -len(tokens & symbols),
                unit.source.path, unit.node.start_byte)
    tests.sort(key=priority)
    selected = tests[:args.max_tests]
    frontend = extract_frontend(sources, patch=patch, test_ids=[u.id for u in selected],
                                max_production_depth=3, max_production_units=256,
                                **selection.get('module_resolution', {}))
    ranks = {unit.id: rank+1 for rank, unit in enumerate(selected)}
    seed_ranking = rank_seeds(frontend, changed, ranks)
    ranks = seed_ranking['ranks']
    corpus = to_emitter_corpus(frontend)
    for test in corpus['tests'].values():
        test['retrieval_rank'] = ranks.get(test['id'])
    for item in [*corpus['capsules'], *corpus['donors']]:
        item['retrieval_rank'] = ranks.get(item['test_id'])
    corpus = augment_corpus(corpus)
    budget = TransformBudget(max_candidates=args.max_candidates, max_pool=args.max_pool,
                             top_k=len(selected), max_donors_per_slot=96,
                             max_sources_per_target=24)
    generated = enumerate_transforms(corpus, frontend, budget)
    cells = generate_cells(corpus, frontend, budget=CellBudget(max_candidates=args.max_candidates // 4))
    sql = generate_embedded_relations(corpus, frontend, budget=EmbeddedRelationBudget(max_candidates=args.max_candidates // 4,
                                                                                    top_k=len(selected)))
    states = generate_state_cells(corpus, budget=StateBudget(max_candidates=args.max_candidates // 4))
    scalars = generate_scalar_cells(corpus, frontend, budget=ScalarBudget(max_candidates=args.max_candidates // 4))
    strings = generate_symbolic_strings(corpus, budget=SymbolicStringBudget(max_candidates=args.max_candidates // 4))
    exceptions = generate_exception_contexts(corpus, frontend, budget=ExceptionBudget(max_candidates=args.max_candidates // 4))
    regex = generate_regex_cells(corpus, frontend, budget=RegexBudget(max_candidates=args.max_candidates // 4))
    contexts = generate_call_contexts(corpus, frontend, budget=ContextBudget(max_candidates=args.max_candidates // 4))
    sequences = generate_sequence_cells(corpus, frontend, budget=SequenceBudget(max_candidates=args.max_candidates // 4))
    producers = generate_producer_contexts(corpus, frontend, budget=ProducerBudget(max_candidates=args.max_candidates // 4))
    compositions = compose_witnesses(corpus, frontend, producers['candidates'] + scalars['candidates'],
                                     budget=CompositionBudget(max_candidates=args.max_candidates // 4))
    generated['candidates'] = annotate_novelty(corpus, frontend, generated['candidates'])
    generated['candidates'] = merge_candidates(generated['candidates'],
                                              cells['candidates']+sql['candidates']+states['candidates']+
                                              scalars['candidates']+strings['candidates']+exceptions['candidates']+
                                              regex['candidates']+contexts['candidates']+sequences['candidates']+
                                              producers['candidates']+compositions['candidates'],
                                              limit=args.max_candidates)
    raw_candidates = generated['candidates']
    for candidate in raw_candidates:
        if candidate.get('target_capsule_id'):
            candidate['source_observation_id'] = candidate['target_capsule_id']
    atomic = atomize_candidates(corpus, frontend, raw_candidates,
                                AtomicBudget(max_candidates=args.max_candidates * 2, max_q_per_candidate=2))
    by_parent = {}
    for candidate in atomic['candidates']:
        by_parent.setdefault(candidate['parent_candidate_id'], []).append(candidate)
    first, rest = [], []
    for candidate in raw_candidates:
        variants = by_parent.get(candidate['id'], [])
        first.append(variants[0] if variants else candidate)
        rest.extend(variants[1:])
    generated['candidates'] = merge_candidates([], first + rest, limit=args.max_candidates)
    generated['relation_cells'] = {k: v for k, v in cells.items() if k not in {'candidates', 'rows'}}
    generated['counts']['candidates'] = len(generated['candidates'])
    generated['counts']['cell_witnesses'] = len(cells['candidates'])
    generated['counts']['sql_witnesses'] = len(sql['candidates'])
    generated['counts']['state_witnesses'] = len(states['candidates'])
    generated['counts']['scalar_witnesses'] = len(scalars['candidates'])
    generated['counts']['symbolic_string_witnesses'] = len(strings['candidates'])
    generated['counts']['exception_witnesses'] = len(exceptions['candidates'])
    generated['counts']['regex_witnesses'] = len(regex['candidates'])
    generated['counts']['call_context_witnesses'] = len(contexts['candidates'])
    generated['counts']['sequence_witnesses'] = len(sequences['candidates'])
    generated['counts']['producer_witnesses'] = len(producers['candidates'])
    generated['counts']['composed_witnesses'] = len(compositions['candidates'])
    generated['counts']['atomic'] = atomic['counts']
    # Hash before and after; concurrent development cannot silently change a frozen batch.
    final_hashes = {name: digest(ROOT/name) for name in source_hashes}
    if source_hashes != final_hashes:
        write(output/'status.json', {'status': 'algorithm_changed_during_preparation', 'case': args.case,
                                    'initial': source_hashes, 'final': final_hashes})
        raise RuntimeError('Algorithm changed during preparation; retain this attempt and start a new directory')
    for path in algorithm_files():
        target = output/'algorithm_snapshot'/path.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(path.read_bytes())
    write(output/'case.json', case)
    write(output/'selection.json', dict(selection, selected_test_ids=[u.id for u in selected],
                                        available_tests=len(tests), test_limit=args.max_tests,
                                        observation_dependency_ranking=seed_ranking))
    write(output/'frontend.json', frontend)
    write(output/'corpus.json', corpus)
    write(output/'candidates.json', generated)
    write(output/'source_cells.json', {k: v for k, v in cells.items() if k != 'candidates'})
    write(output/'generation_domains.json', {'sql': {k:v for k,v in sql.items() if k != 'candidates'},
                                            'state': {k:v for k,v in states.items() if k != 'candidates'},
                                            'scalar': {k:v for k,v in scalars.items() if k != 'candidates'},
                                            'symbolic_string': {k:v for k,v in strings.items() if k != 'candidates'},
                                            'exception': {k:v for k,v in exceptions.items() if k != 'candidates'},
                                            'regex': {k:v for k,v in regex.items() if k != 'candidates'},
                                            'call_context': {k:v for k,v in contexts.items() if k != 'candidates'},
                                            'sequence': {k:v for k,v in sequences.items() if k != 'candidates'},
                                            'producer': {k:v for k,v in producers.items() if k != 'candidates'},
                                            'composition': {k:v for k,v in compositions.items() if k != 'candidates'},
                                            'atomic': {k:v for k,v in atomic.items() if k != 'candidates'}})
    (output/'issue.md').write_bytes(Path(case['issue']).read_bytes())
    files = ['case.json','selection.json','frontend.json','corpus.json','candidates.json',
             'source_cells.json','generation_domains.json','issue.md']
    manifest = {'status':'prepared','case':args.case,'created_at':datetime.now(timezone.utc).isoformat(),
                'algorithm_sha256':source_hashes,'files_sha256':{name:digest(output/name) for name in files},
                'elapsed_seconds':time.monotonic()-started, 'budget':asdict(budget),
                'model_calls':0,'reference_or_verifier_inputs':False,'execution_outcomes':False,
                'frontend_stats':frontend['stats'],'candidate_counts':generated.get('counts',{}),
                'stage':'static_hypotheses_not_verified_gap_detection'}
    write(output/'prepare.json',manifest)
    write(output/'status.json',{'status':'prepared','case':args.case})
    return manifest


def main():
    p=argparse.ArgumentParser()
    p.add_argument('stage',choices=['prepare'])
    p.add_argument('--case',required=True)
    p.add_argument('--registry',type=Path,default=ROOT/'data/relational_gap_v1/registry.json')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-tests',type=int,default=256)
    p.add_argument('--max-candidates',type=int,default=512)
    p.add_argument('--max-pool',type=int,default=8192)
    args=p.parse_args()
    result=prepare(args)
    print(json.dumps({k:v for k,v in result.items() if k not in {'files_sha256','algorithm_sha256'}},ensure_ascii=False))


if __name__=='__main__':
    main()
