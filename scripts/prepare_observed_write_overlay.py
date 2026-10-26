"""Prepare all selected Python q probes in emitted artifacts; never execute them."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from prototypes.observed_write_runtime import build_plan, instrument_sources
from relation_search.checkpoint import digest, read, write


def prepare_group(source_manifest, output, *, map_origins=False):
    manifest = read(source_manifest)
    corpus_path = Path(manifest['original_input'])/'corpus.json'
    corpus = read(corpus_path)
    original_mounts = {row['target']:row for row in manifest['mounts']}
    result, mounts, counts = deepcopy(manifest), {}, []
    for phase in result['phases']:
        role = phase['role']
        folder = output/role
        items = (manifest['controls'] if role=='control' else
                 manifest.get('profile_obligations', []) if role=='source_profile'
                 else manifest['obligations'])
        functions = defaultdict(list)
        for item in items:
            functions[item['path']].append(item['test_name'])
        sources = dict(corpus['sources'])
        for snapshot in phase['files']:
            original = original_mounts[snapshot['staged']]
            if digest(original['source']) != snapshot['sha256']:
                raise ValueError('Original emitted snapshot changed')
            sources[snapshot['target']] = {'code':Path(original['source']).read_text()}
        plan = build_plan(sources, assertion_paths=functions, assertion_functions=functions)
        if map_origins:
            from prototypes.emitted_q_origin import bind_plan_origins
            accepted=read(source_manifest.parent.parent/'accepted.json')
            plan=bind_plan_origins(plan,corpus,sources,items,accepted)
            write(folder/'source_q_mapping.json',plan['source_q_mapping'])
        overlay = instrument_sources(sources, plan)
        write(folder/'instrumentation.json', plan)
        originals = {row['target']:row for row in phase['files']}
        new_files = []
        for path in sorted(set(originals)|set(overlay)|{'__observed_write_runtime.py'}):
            if path in overlay or path=='__observed_write_runtime.py':
                target = folder/'files'/path
                target.parent.mkdir(parents=True, exist_ok=True)
                if path in overlay:
                    target.write_text(overlay[path])
                else:
                    shutil.copyfile(ROOT/'prototypes/observed_write_runtime.py', target)
                staged = '.relational_phase_inputs/'+role+'/observed_'+hashlib.sha256(path.encode()).hexdigest()+'.snapshot'
                row = dict(target=path, staged=staged, sha256=digest(target))
                mounts[staged] = dict(source=str(target.resolve()), target=staged, sha256=digest(target))
            else:
                row = originals[path]
                mounts[row['staged']] = original_mounts[row['staged']]
            new_files.append(row)
        phase['files'] = new_files
        phase['command'] = 'export OBSERVED_WRITE_TRACE="$COMBINATION_REPORT_DIR/observed_writes.jsonl"\n'+phase['command']
        counts.append(dict(role=role, selected_tests=len(items),
            enumerated_q=len(plan['enumerated_assertions']),
            instrumented_q=len({json.dumps(row['q_span'],sort_keys=True) for row in plan['queries']}),
            instrumented_reads=len(plan['queries']), writers=len(plan['writes']),
            unsupported=dict(Counter(row['reason'] for row in plan['unsupported'])),
            transformed_files=len(overlay),
            source_q_mapping=plan.get('source_q_mapping',{}),
            instrumentation=str((folder/'instrumentation.json').resolve())))
    write(output/'phase_plan.json', dict(phases=result['phases']))
    mounts['.relational_phase_inputs/plan.json'] = dict(
        target='.relational_phase_inputs/plan.json',
        source=str((output/'phase_plan.json').resolve()), sha256=digest(output/'phase_plan.json'))
    mounts['.relational_phase_inputs/runner.py'] = original_mounts['.relational_phase_inputs/runner.py']
    result['mounts'] = list(mounts.values())
    result['observation_overlay'] = dict(source_manifest=str(source_manifest.resolve()),
        source_manifest_sha256=digest(source_manifest), source_corpus_sha256=digest(corpus_path),
        prepared_only=True, original_assertions_unchanged=True,
        all_selected_tests_considered=True,
        q_source_identity='exact clone byte-edit source provenance' if map_origins else 'actual original emitted source spans',
        cross_candidate_original_q_mapping='only explicitly mapped q and allocation spans' if map_origins else 'not implemented; do not equate or score different emitted spans',
        phases=counts)
    write(output/'manifest.json', result)
    return counts


def prepare(emitted_paths, output, *, map_origins=False):
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    inputs = []
    for emitted in emitted_paths:
        for artifact in read(emitted/'artifacts.json'):
            source = Path(artifact)/'manifest.json'
            inputs.append(dict(path=str(source.resolve()), sha256=digest(source)))
    code = [ROOT/'prototypes/observed_write_runtime.py',
            ROOT/'prototypes/assertion_write_origin.py', ROOT/'prototypes/emitted_q_origin.py',
            ROOT/'generic_composition/emitter.py', Path(__file__).resolve()]
    write(output/'protocol.json', dict(inputs=inputs, subject_executions=0,
        provider_calls=0, target_labels_used=False,
        map_origins=map_origins,
        enumeration='every selected control/profile/generated test in every supplied artifact',
        code_sha256={str(p.relative_to(ROOT)):digest(p) for p in code}))
    for path in code:
        destination=output/'algorithm_snapshot'/path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path,destination)
    for i, row in enumerate(inputs):
        source = Path(row['path'])
        case = read(source)['case']
        folder=output/case/f'group_{i:03d}'
        counts=prepare_group(source, folder,map_origins=map_origins)
        summaries.append(dict(case=case, manifest=str((folder/'manifest.json').resolve()), phases=counts))
        print(json.dumps(dict(case=case, group=i,
            q=sum(row['instrumented_q'] for row in counts),
            enumerated=sum(row['enumerated_q'] for row in counts))), flush=True)
    write(output/'summary.json', dict(groups=summaries, subject_executions=0, provider_calls=0))
    write(output/'seal.json', dict(files_sha256={str(p.relative_to(output)):digest(p)
          for p in sorted(output.rglob('*')) if p.is_file() and p.name!='seal.json'}))
    return summaries


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--emitted',type=Path,nargs='+',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--map-origins',action='store_true')
    args=parser.parse_args()
    prepare(args.emitted,args.output,map_origins=args.map_origins)
