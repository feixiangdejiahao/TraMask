"""Independent v3 campaign audit with eligible and actually-offered queue semantics.

Uses the existing native execution verifier. No generator or model imports.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

import evaluate_relation_search_continuation as prior
from evaluate_relation_search import read
from evaluate_relational_gap import digest, freeze_file, verify_file

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'results/relation_search_20260929_v3/evaluation'


def verify_semantic_frontier(directory, stage, configuration, history, ignored_selected,
                             previous_sha256, source_identity, model_result):
    frontier_path, selection_path = directory/'semantic_frontier.json', directory/'semantic_selection.json'
    frontier, selection = read(frontier_path), read(selection_path)
    evidence = [freeze_file(frontier_path), freeze_file(selection_path)]
    index = int(directory.parent.name.removeprefix('round_'))
    served = set()
    prior_ok = previous_sha256 is None
    if index:
        previous = directory.parent.parent/f'round_{index-1:03d}'/'semantic'/'semantic_frontier.json'
        evidence.append(freeze_file(previous))
        prior_ok = digest(previous) == previous_sha256
        served = set(read(previous)['selected_ids'])
    ranking, catalogue = selection.get('ranking', []), frontier.get('candidates', [])
    ranked = [row['id'] for row in ranking]
    eligibility = configuration.get('semantic_policy', 'shape')
    eligible = [row['id'] for row in ranking if row['id'] not in served and
                (eligibility == 'shape' or row.get('evidence', {}).get('eligible') is True)]
    chosen = selection.get('selected', [])
    chosen_ids = [row['id'] for row in chosen]
    offered = selection.get('offered_ids', chosen_ids)
    budget = configuration['semantic_budget']
    pending = [identifier for identifier in eligible if identifier not in set(offered)]
    actual_offered = set()
    for path in sorted((directory/'requests').glob('request_*.json')):
        request = read(path)
        actual_offered.update(row['candidate']['id'] for row in request.get('offered', {}).values())
        evidence.append(freeze_file(path))
        wire_path = directory/'completions'/path.stem/'request.json'
        if wire_path.exists():
            wire = read(wire_path)
            assert wire['messages'] == [{'role':'system','content':request['system']},
                                        {'role':'user','content':request['prompt']}], 'Provider wire differs from prepared prompt'
            assert wire['model'] == 'deepseek-v4-flash', 'Unexpected provider model'
            evidence.append(freeze_file(wire_path))
        if configuration.get('oracle_evidence') == 'dependency':
            assert request.get('evidence_mode') == 'dependency'
            prompt = json.loads(request['prompt'])
            assert all('dependency_evidence' in row for row in prompt['candidates'])
    checks = [prior_ok,
        stage.get('previous_semantic_sha256') == previous_sha256,
        set(stage.get('previously_selected', [])) == served,
        frontier.get('policy') == selection.get('policy') == configuration.get('semantic_frontier_policy'),
        stage.get('semantic_frontier_policy') == configuration.get('semantic_frontier_policy'),
        frontier.get('source_identity') == source_identity,
        len(catalogue) == len({row['id'] for row in catalogue}) == len(history),
        {row['id']:row for row in catalogue} == history,
        len(ranked) == len(set(ranked)) == len(history) and set(ranked) == set(history),
        all(row.get('previously_selected') == (row['id'] in served) for row in ranking),
        chosen_ids == eligible[:budget] == model_result.get('selected_ids', []),
        all(row == history.get(row['id']) for row in chosen),
        all(row.get('selected') == (row['id'] in chosen_ids) for row in ranking),
        set(offered) == actual_offered == set(model_result.get('offered_ids', chosen_ids)),
        set(offered) <= set(chosen_ids),
        selection.get('selected_but_unoffered_ids', []) == [x for x in chosen_ids if x not in set(offered)],
        set(frontier.get('selected_ids', [])) == served | set(offered),
        set(model_result.get('previous_selected', [])) == served | set(offered),
        frontier.get('pending_ids') == pending,
        selection.get('budget') == budget,
        selection.get('catalogue_count') == len(history),
        selection.get('eligible_count') == len(eligible),
        selection.get('selected_count') == len(chosen),
        selection.get('pending_count') == model_result.get('pending_semantic_count') == len(pending),
        model_result.get('semantic_frontier_policy') == configuration.get('semantic_frontier_policy'),
        stage.get('selection_policy', 'shape') == eligibility,
        stage.get('evidence_mode', 'baseline') == configuration.get('oracle_evidence', 'baseline'),
    ]
    return all(checks), evidence, digest(frontier_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, default=OUT/'ledger.json')
    parser.add_argument('--deliveries', type=Path, required=True)
    parser.add_argument('--reviews', type=Path, required=True)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    prior.OUT=OUT
    prior.verify_semantic_frontier=verify_semantic_frontier
    print(json.dumps(prior.audit(args)))


if __name__=='__main__':
    main()
