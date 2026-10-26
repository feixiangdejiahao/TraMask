"""Uniform, recorded JSON metadata / unambiguous hash-reference recovery.

The original strict experiment stays immutable. No goal, oracle, test expression,
or provider prompt is rewritten. Native results never enter this supplement.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_automatic_augmentation_pilot as pilot
from scripts import execute_automatic_augmentation_pilot as executor

VERSION = 'automatic-augmentation-lossless-transport.v1'
HEX_REF = re.compile(r'^(seed|test|source|declaration)_([0-9a-f]{16,64})$')


def canonical_reference(value, permitted, candidates):
    if not isinstance(value, str) or value in permitted:
        return value
    match = HEX_REF.fullmatch(value)
    if not match:
        return value
    kind, suffix = match.groups()
    # Short content hashes are accepted only when they identify exactly one
    # supplied object in this batch. This is not edit-distance/fuzzy matching.
    matches = [p for p in permitted if p.startswith(kind + '_' + suffix)]
    if kind == 'seed':
        # The seed alias uses 20 digest digits; its matching test receipt uses
        # 24. Accept the exact longer digest, not arbitrary trailing characters.
        matches += [c['seed_alias'] for c in candidates
                    if c.get('evidence_id', '').startswith('test_')
                    and value == 'seed_' + c['evidence_id'][5:]
                    and c['seed_alias'] in permitted]
    matches = sorted(set(matches))
    return matches[0] if len(matches) == 1 else value


def normalize(content, candidates, known_evidence, stage='judgment'):
    obj = json.loads(content, object_pairs_hook=pilot._unique_object)
    before = deepcopy(obj)
    changes = []
    if not isinstance(obj, dict):
        return obj, changes
    required = {'assessments', 'goals'} if stage == 'judgment' else {'tests'}
    if set(obj) == required | {'type'} and obj['type'] == 'json_object':
        del obj['type']
        changes.append(dict(path='type', before='json_object', after=None,
                            rule='remove_redundant_exact_transport_metadata'))
    aliases = {c['seed_alias'] for c in candidates}
    def change(row, key, permitted, path):
        if not isinstance(row, dict) or key not in row:
            return
        original = row[key]
        values = original if isinstance(original, list) else [original]
        mapped = [canonical_reference(v, permitted, candidates) for v in values]
        replacement = mapped if isinstance(original, list) else mapped[0]
        if replacement != original:
            changes.append(dict(path=path + '.' + key, before=original, after=replacement,
                                rule='unique_supplied_content_hash_identity'))
            row[key] = replacement
    if stage == 'judgment':
        for i, row in enumerate(obj.get('assessments', []) if isinstance(obj.get('assessments'), list) else []):
            change(row, 'seed_aliases', aliases, f'assessments[{i}]')
            change(row, 'evidence_ids', known_evidence, f'assessments[{i}]')
        for i, row in enumerate(obj.get('goals', []) if isinstance(obj.get('goals'), list) else []):
            change(row, 'seed_alias', aliases, f'goals[{i}]')
            change(row, 'evidence_ids', known_evidence, f'goals[{i}]')
    else:
        for i, row in enumerate(obj.get('tests', []) if isinstance(obj.get('tests'), list) else []):
            change(row, 'seed_alias', aliases, f'tests[{i}]')
    # The only mutable leaves are recorded above. Deep copying prevents changes
    # to the stored provider response; literal text is preserved verbatim.
    assert before is not obj
    return obj, changes


def frozen_protocol(root):
    original = pilot.load_protocol(root)
    directory = root / 'transport_normalized'
    if not (directory / 'prepared.json').exists():
        pilot.write(directory / 'prepared.json', dict(version=VERSION,
            original_protocol=pilot.receipt(root / 'prepared.json'), algorithm=pilot.receipt(__file__),
            scope='Apply uniformly to all complete original responses, both arms and all repeats.',
            rules=['Remove only extra top-level type=json_object metadata when other top-level keys exactly match.',
                   'Resolve >=16-digit hash prefixes only to a unique supplied evidence/seed ID.',
                   'An expanded seed digest must exactly equal its own supplied 24-digit test digest.'],
            forbidden=['No fuzzy matching, goal text changes, oracle edits, code edits or outcome feedback.',
                       'No recovery of truncated responses, missing keys, conflicting or ambiguous identities.'],
            generation='Use unchanged frozen generation system and original input payload, plus mechanically recovered goals.',
            strict_results='Original results are preserved and reported separately. No repeat of judgment provider calls.'))
        pilot.write(directory / 'seal.json', pilot.receipt(directory / 'prepared.json'))
    pilot.verify(pilot.read(directory / 'seal.json'))
    pilot.verify(pilot.read(directory / 'prepared.json')['algorithm'])
    return original, directory


def recover_item(root, target, case, batch, arm, repeat):
    suffix = Path('cases') / case['case'] / batch['batch_id'] / arm / f'repeat_{repeat}'
    old, dest = root / suffix, target / suffix
    if not (old / 'result.json').exists():
        return None
    if (dest / 'result.json').exists():
        pilot.verify(pilot.read(dest / 'result_seal.json'))
        return pilot.read(dest / 'result.json')
    pilot.verify(pilot.read(old / 'result_seal.json'))
    strict = pilot.read(old / 'result.json')
    pilot.verify(strict['judgment'])
    payload = pilot.read((batch['source_payload'] if arm == 'source_only' else batch['history_payload'])['path'])
    manifest = pilot.read(old / 'judgment/completion/manifest.json')
    path = old / 'judgment/completion/completion.txt'
    decision = dict(status='unknown', assessments=[], goals=[], issues=['incomplete_provider_response'])
    changes = []
    normalized = None
    if manifest.get('finish_reason') == 'stop' and path.exists():
        try:
            normalized, changes = normalize(path.read_text(), batch['candidates'], pilot.evidence_ids(payload))
            decision = pilot.parse_judgment(pilot.canonical(normalized), 'stop',
                {c['seed_alias'] for c in batch['candidates']}, pilot.evidence_ids(payload))
        except (ValueError, TypeError) as exc:
            decision['issues'] = [str(exc)]
    pilot.write(dest / 'judgment/normalization.json', dict(original_response=pilot.receipt(path) if path.exists() else None,
                                                         transformations=changes, response=normalized))
    pilot.write(dest / 'judgment/decision.json', decision)
    pilot.write(dest / 'judgment/decision_seal.json', pilot.receipt(dest / 'judgment/decision.json'))
    result = dict(case=case['case'], batch=batch['batch_id'], arm=arm, repeat=repeat,
        original_result=pilot.receipt(old / 'result.json'), strict_judgment_status=strict['judgment_status'],
        judgment_status=decision['status'], judgment=pilot.receipt(dest / 'judgment/decision.json'),
        transformations=len(changes), goals=len(decision['goals']),
        provider_calls=0, measured_tokens=0, usage_missing=0, candidates=0, generation_status='not_requested')
    if decision['goals']:
        pilot.verify(pilot.read(dest / 'judgment/decision_seal.json'))
        if strict['goals']:
            # The same request was already made in the strict branch. Reuse
            # that response, then apply the same generation transport rules.
            original = pilot.read(old / 'judgment/decision.json')
            if original['goals'] != decision['goals']:
                raise ValueError('normalization_changed_an_accepted_goal')
            meta = pilot.read(old / 'generation/completion/manifest.json')
            response_path = old / 'generation/completion/completion.txt'
            response = response_path.read_text() if response_path.exists() else ''
            result['generation_source'] = 'existing_strict_request'
            completion = old / 'generation/completion'
        else:
            req = pilot.request(pilot.GENERATION_SYSTEM, dict(original_evidence=payload, frozen_goals=decision['goals']), 'generation')
            response, meta = pilot.dispatch_once(req, dest / 'generation')
            completion = dest / 'generation/completion'
            result.update(generation_source='new_request_after_recovered_judgment',
                provider_calls=meta.get('external_model_calls', 0),
                measured_tokens=(meta.get('usage') or {}).get('total_tokens', 0), usage_missing=int(not meta.get('usage')))
        normalized_generation = None
        generation_changes = []
        if meta.get('finish_reason') == 'stop':
            try:
                normalized_generation, generation_changes = normalize(response, batch['candidates'], pilot.evidence_ids(payload), 'generation')
            except (ValueError, TypeError):
                pass
        pilot.write(dest / 'generation/normalization.json', dict(completion_manifest=pilot.receipt(completion / 'manifest.json'),
            transformations=generation_changes, response=normalized_generation))
        corpus = pilot.read(case['inputs']['corpus.json']['path'])
        decode_case = dict(case=case['case'], source=case['source'], repository=case['repository'],
                           seeds=batch['candidates'], goals=decision['goals'])
        decoded = executor.decode(corpus, decode_case,
            pilot.canonical(normalized_generation) if normalized_generation is not None else response, meta.get('finish_reason'))
        pilot.write(dest / 'generation/decoded.json', decoded)
        for index, candidate in enumerate(decoded['candidates'], 1):
            pilot.write(dest / 'generation' / f'candidate_{index:02d}' / 'program.json', candidate)
        result.update(generation_status=decoded['status'], candidates=len(decoded['candidates']),
                      decoded=pilot.receipt(dest / 'generation/decoded.json'), rejected=decoded.get('rejected', []))
    pilot.write(dest / 'result.json', result)
    pilot.write(dest / 'result_seal.json', pilot.receipt(dest / 'result.json'))
    print(pilot.canonical(result), flush=True)
    return result


def run(root, workers=3):
    original, target = frozen_protocol(root)
    items = [(root, target, c, b, a, r) for r in range(1, original['repeats'] + 1)
             for c in original['cases'] for b in c['batches'] for a in original['arms']]
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for future in as_completed([pool.submit(recover_item, *args) for args in items]):
            value = future.result()
            if value is not None:
                results.append(value)
    summary = dict(version=VERSION, available_originals=len(results), planned_originals=len(items),
        provider_calls=sum(r['provider_calls'] for r in results), measured_tokens=sum(r['measured_tokens'] for r in results),
        usage_missing=sum(r['usage_missing'] for r in results), candidates=sum(r['candidates'] for r in results),
        results=sorted(results, key=lambda r: (r['case'], r['batch'], r['arm'], r['repeat'])))
    # Snapshots are monotonic, named by number of available completed originals.
    pilot.write(target / f'summary_{len(results):03d}.json', summary)
    return {k: v for k, v in summary.items() if k != 'results'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--root', type=Path, default=pilot.DEFAULT_OUTPUT)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    print(pilot.canonical(run(args.root, args.workers)))
