"""Source-only paired generation census from a pre-frozen source inventory.

No candidate truth, native outcomes, provider, verifier, or reference is read.
The generator is imported only after its required source hashes are checked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ''}:
    sys.path.insert(0, str(ROOT))


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def freeze(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))


def require(value, message):
    if not value:
        raise ValueError(message)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def local_modules():
    result = {}
    for module in list(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT) and path.suffix == '.py' and '.venv' not in path.parts:
                result[str(path)] = sha(path)
    return result


def verify_modules(seals):
    for path, digest in seals.items():
        require(sha(path) == digest, 'Generator/dependency source changed: ' + path)


def verify_receipt(result, mode, expected_budget):
    """Check traversal/count receipts independently of the generator helpers."""
    require(result['mode'] == mode and result['budget'] == expected_budget,
            'Mode or budget differs from frozen protocol')
    require(result['provider_calls'] == result['native_executions'] == 0, 'Unexpected execution claim')
    planned, attempted = result['scheduled_pairs'], result['attempted_pairs']
    require(result['scheduled_pair_count'] == len(planned) <= expected_budget['max_attempts'],
            'Planned traversal exceeds fixed attempt cap')
    require(result['attempts'] == len(attempted) <= len(planned) and attempted == planned[:len(attempted)],
            'Actual traversal must be a prefix of the frozen planned schedule')
    require(len(result['candidates']) <= min(len(attempted), expected_budget['max_candidates']),
            'Candidate count exceeds attempts or frozen candidate cap')
    if 'pair_skipped' in result:
        require(sum(result['pair_skipped'].values()) + len(result['candidates']) == len(attempted),
                'Pair outcomes do not sum to the actual attempted pair denominator')
        keys = set(result['preprocessing_skipped']) | set(result['pair_skipped'])
        require(result['skipped'] == {key: result['preprocessing_skipped'].get(key, 0)
                + result['pair_skipped'].get(key, 0) for key in keys}, 'Skip stage accounting mismatch')
    for rows, field in [(planned, 'pair_schedule_sha256'), (attempted, 'attempted_pair_schedule_sha256')]:
        digest = data_sha(rows)
        require(result[field] == digest, 'Pair schedule hash does not match receipt: ' + field)


def ast_hash(code, language, path):
    """Independent parser fingerprint: includes operators, ignores comments/space."""
    from tree_sitter import Language, Parser
    import tree_sitter_go
    import tree_sitter_python
    import tree_sitter_typescript
    grammar = {'python': tree_sitter_python.language, 'go': tree_sitter_go.language,
               'typescript': (tree_sitter_typescript.language_tsx if path.endswith('.tsx')
                              else tree_sitter_typescript.language_typescript)}[language]
    tree = Parser(Language(grammar())).parse(code)
    require(not tree.root_node.has_error, 'Generated/original source parse error: ' + path)
    stack = [(tree.root_node, False)]
    digest = hashlib.sha256()
    while stack:
        node, end = stack.pop()
        if node.type == 'comment':
            continue
        if end:
            digest.update(b')')
            continue
        digest.update(b'(' + node.type.encode() + b':')
        if node.children:
            stack.append((node, True))
            stack.extend((child, False) for child in reversed(node.children))
        else:
            token = code[node.start_byte:node.end_byte]
            digest.update(str(len(token)).encode() + b':' + token + b')')
    return digest.hexdigest()


def audit_candidate(candidate, corpus, output):
    selected = corpus['tests'][candidate['base_test_id']]['span']
    owner = selected['path']
    require(not Path(owner).is_absolute() and '..' not in Path(owner).parts,
            'Source path must stay inside generated artifact directory')
    require(candidate['id'] == Path(candidate['id']).name and candidate['id'] not in {'.', '..', ''},
            'Candidate identifier must be a safe directory name')
    original = corpus['sources'][owner]['code'].encode()
    modified = original
    require(not candidate.get('imports'), 'Unexpected imports in address experiment')
    edits = sorted(candidate['edits'], key=lambda edit: edit['span']['start_byte'], reverse=True)
    require(len(edits) == 1, 'Expected exactly one generated action insertion')
    for edit in edits:
        extent = edit['span']
        begin, end = extent['start_byte'], extent['end_byte']
        require(extent['path'] == owner and selected['start_byte'] <= begin == end <= selected['end_byte']
                and edit['before'] == '', 'Generated action must only insert inside the fixed original test')
        modified = modified[:begin] + edit['after'].encode() + modified[end:]
    refs = []
    def visit(value):
        if isinstance(value, dict):
            if {'path', 'start_byte', 'end_byte'} <= set(value):
                source = corpus['sources'][value['path']]['code'].encode()
                begin, end = value['start_byte'], value['end_byte']
                require(0 <= begin <= end <= len(source), 'Source evidence reference outside frozen corpus')
                refs.append(dict(path=value['path'], start_byte=begin, end_byte=end,
                                 excerpt_sha256=hashlib.sha256(source[begin:end]).hexdigest()))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(candidate['provenance'])
    before = ast_hash(original, candidate['language'], owner)
    after = ast_hash(modified, candidate['language'], owner)
    generated = output / 'programs' / candidate['id'] / owner
    generated.parent.mkdir(parents=True, exist_ok=True)
    with generated.open('xb') as stream:
        stream.write(modified)
    return dict(id=candidate['id'], base_test_id=candidate['base_test_id'], source_path=owner,
        original_source_sha256=hashlib.sha256(original).hexdigest(), generated_source=freeze(generated),
        original_ast_sha256=before, generated_ast_sha256=after, ast_novel=before != after,
        original_source_bytes_retained=True, source_references=refs,
        key_substitution=candidate['provenance'].get('key_substitution'),
        source_address_connection=candidate['relation']['effect'], native_influence='not_measured',
        oracle_validity='unassessed', candidate_selection_source='new_generation_from_original_source')


def run(args):
    for filename, expected in [('experimental/observation_address_join.py', args.generator_sha),
                               ('experimental/observation_address_effects.py', args.effects_sha)]:
        require(sha(ROOT / filename) == expected, 'Generator freeze mismatch: ' + filename)
    generator = importlib.import_module('experimental.observation_address_join')
    importlib.import_module('experimental.observation_address_effects')
    seals = local_modules()
    inventory = read(args.inventory)
    require(inventory['case_count'] == 17 and len(inventory['cases']) == 17, 'Expected frozen17 source cases')
    protocol = read(args.protocol)
    require(protocol['inventory']['sha256'] == sha(args.inventory), 'Protocol inventory hash mismatch')
    require(protocol['case_order'] == [entry['case'] for entry in inventory['cases']], 'Frozen case order mismatch')
    expected_budget = dict(max_candidates=16, max_attempts=128, max_actions_per_group=32)
    require(protocol['budget'] == expected_budget, 'Protocol budget mismatch')
    budget = generator.JoinBudget(max_candidates=16, max_attempts=128, max_actions_per_group=32)
    results = []
    started = time.monotonic()
    write(args.output / 'protocol.json', dict(inventory=freeze(args.inventory),
        protocol=freeze(args.protocol), evaluator=freeze(__file__), initial_source_seals=seals,
        source_only=True, provider_calls=0, native_executions=0))
    for entry in inventory['cases']:
        for kind in ('corpus', 'frontend'):
            require(sha(entry[kind]['path']) == entry[kind]['sha256'], 'Source inventory changed')
        corpus, frontend = read(entry['corpus']['path']), read(entry['frontend']['path'])
        input_data_seals = dict(corpus=data_sha(corpus), frontend=data_sha(frontend))
        variants = {}
        for mode in ('receiver_only', 'address'):
            verify_modules(seals)
            t0 = time.monotonic()
            result = generator.generate(corpus, frontend, mode=mode, budget=budget)
            require(input_data_seals == dict(corpus=data_sha(corpus), frontend=data_sha(frontend)),
                    'Generator mutated the frozen input data between paired modes')
            verify_receipt(result, mode, expected_budget)
            path = args.output / entry['case'] / (mode + '.json')
            write(path, result)
            audits = [audit_candidate(candidate, corpus, path.parent / mode) for candidate in result['candidates']]
            audit_path = path.parent / (mode + '_independent_source_audit.json')
            write(audit_path, dict(candidates=audits, no_native_or_oracle_claim=True))
            variants[mode] = dict(output=freeze(path), independent_audit=freeze(audit_path),
                seconds=time.monotonic() - t0, attempts=result['attempts'], candidates=len(audits),
                ast_novel=sum(row['ast_novel'] for row in audits),
                unique_ast_candidates=len({(row['base_test_id'], row['generated_ast_sha256']) for row in audits}),
                skipped=result['skipped'], action_bank_count=result['action_bank_count'],
                preprocessing_skipped=result['preprocessing_skipped'], pair_skipped=result['pair_skipped'],
                scheduled_pair_count=result['scheduled_pair_count'],
                demand_count=result['demand_count'], action_bank_sha256=result['action_bank_sha256'],
                pair_schedule_sha256=result['pair_schedule_sha256'],
                attempted_pairs=result['attempted_pairs'], budget_exhausted=result['budget_exhausted'],
                key_substitutions=sum(bool(row['key_substitution']) for row in audits),
                changed_key_values=sum(bool(row['key_substitution'])
                    and (type(row['key_substitution']['old_value']) is not type(row['key_substitution']['new_value'])
                         or row['key_substitution']['old_value'] != row['key_substitution']['new_value']) for row in audits),
                ast_ids=[(row['base_test_id'], row['generated_ast_sha256']) for row in audits])
            verify_modules(seals)
            seals.update(local_modules())
        left, right = variants['receiver_only'], variants['address']
        for field in ('action_bank_sha256', 'pair_schedule_sha256', 'action_bank_count', 'demand_count'):
            require(left[field] == right[field], 'Paired source bank/schedule mismatch: ' + field)
        common = min(len(left['attempted_pairs']), len(right['attempted_pairs']))
        require(left['attempted_pairs'][:common] == right['attempted_pairs'][:common], 'Attempted pairs not shared prefixes')
        lhs, rhs = set(map(tuple, left['ast_ids'])), set(map(tuple, right['ast_ids']))
        results.append(dict(case=entry['case'], language=entry['language'], variants=variants,
            input_data_seals=input_data_seals, input_data_unchanged=True,
            shared_ast_candidates=len(lhs & rhs), address_only_ast_candidates=len(rhs - lhs),
            receiver_only_ast_candidates=len(lhs - rhs), shared_bank_and_schedule_verified=True))
        print(json.dumps(dict(case=entry['case'], receiver_only_candidates=left['candidates'],
            address_candidates=right['candidates'], receiver_only_attempts=left['attempts'],
            address_attempts=right['attempts'], address_new_ast=len(rhs - lhs))), flush=True)
    verify_modules(seals)
    write(args.output / 'manifest.json', dict(version='independent-observation-action-source-census.v1',
        created_utc=datetime.now(timezone.utc).isoformat(), seconds=time.monotonic()-started,
        inventory=freeze(args.inventory), protocol=freeze(args.protocol), evaluator=freeze(__file__),
        source_seals=seals, fixed_case_denominator=17, budget=dict(max_candidates=16,max_attempts=128,max_actions_per_group=32),
        cases=results, provider_calls=0,native_executions=0, oracle_validity='unassessed',
        native_influence='not_measured', valid_gap_retention='not_measured', false_positive_reduction='not_measured'))
    print(json.dumps(dict(manifest=freeze(args.output / 'manifest.json'))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    for name in ('inventory', 'protocol', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--generator-sha', required=True)
    parser.add_argument('--effects-sha', required=True)
    run(parser.parse_args())
