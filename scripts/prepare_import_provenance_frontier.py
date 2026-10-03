"""Apply donor-import repair to every parent in a frozen prefix cohort."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import read
from relation_search import import_provenance_repair
from relation_search.candidate_edit_transport import verify_emission
from scripts.run_contract_repair_search import frozen, verify, write
from scripts.run_type_projection_component import emit


def prepare(args):
    verify(read(args.prefixes / 'seal.json'))
    p = read(args.prefixes / 'prepared.json')
    args.output.mkdir(parents=True, exist_ok=False)
    cache, records, changed = {}, [], []
    for index, item in enumerate(p['items']):
        originals = [entry for entry in item['programs'] if entry['is_original']]
        if len(originals) != 1:
            raise ValueError('Each parent must have exactly one original fallback')
        entry = originals[0]
        verify(entry['program'])
        for receipt in item['source_inputs'].values():
            verify(receipt)
        source = item['source_inputs']['corpus']['path']
        if source not in cache:
            cache[source] = read(source)
        corpus = cache[source]
        analysis = import_provenance_repair.repair(corpus, read(entry['program']['path']))
        candidate = analysis.pop('candidate')
        record = dict(name=item['name'], case=item['case'], original=entry['program'],
                      source_inputs=item['source_inputs'], analysis=analysis)
        if analysis['changes']:
            directory = args.output / 'cases' / item['case'] / f'candidate_{index + 1:04d}'
            write(directory / 'program.json', candidate)
            artifact = emit(candidate, Path(item['source']), directory / 'native', {'timeout': 180})
            transport = verify_emission(corpus, candidate, artifact)
            if transport['status'] != 'matched':
                raise ValueError('Repaired candidate test-body transport mismatch')
            manifest = read(artifact / 'manifest.json')
            obligation = manifest['obligations'][0]
            emitted = Path(transport['emitted_source']['path']).read_text()
            bindings = import_provenance_repair.verify_bindings(corpus, candidate, obligation['path'], emitted)
            if bindings['status'] != 'matched':
                raise ValueError('Repaired generated import identity mismatch')
            write(directory / 'transport.json', dict(body=transport, imports=bindings))
            record.update(program=frozen(directory / 'program.json'), artifact=frozen(artifact / 'manifest.json'),
                          transport=frozen(directory / 'transport.json'))
            changed.append(record)
        records.append(record)
    result = dict(version=import_provenance_repair.VERSION,
        source_prepared=frozen(args.prefixes / 'prepared.json'),
        builder=frozen(Path(__file__)), repair=frozen(Path(import_provenance_repair.__file__)),
        parents=len(records), changed_parents=len(changed), records=records,
        selection='Every original whole-test parent from the supplied cohort; no native results or labels read.',
        subject_executions=0, external_model_calls=0, detector_alerts=0,
        created_utc=datetime.now(timezone.utc).isoformat())
    write(args.output / 'cohort.json', result)
    return dict(parents=len(records), changed_parents=len(changed), cohort=frozen(args.output / 'cohort.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--prefixes', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(prepare(parser.parse_args())))
