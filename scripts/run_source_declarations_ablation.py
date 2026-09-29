"""Dispatch a sealed source-presentation comparison once per prepared case."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search.checkpoint import digest, read, write

TERMINAL_STATUSES = {'complete', 'error', 'configuration_error'}


def verified_records(output):
    output = Path(output).resolve()
    protocol, ready = read(output/'stage.json'), read(output/'ready.json')
    if ready['status'] != 'ready' or ready['prepared'] != len(protocol['cases']):
        raise ValueError('All preregistered case requests must be ready')
    if [row['case'] for row in ready['records']] != protocol['cases']:
        raise ValueError('Prepared cases differ from the fixed case order')
    for path, checksum in protocol['code_sha256'].items():
        if digest(path) != checksum:
            raise ValueError('Prepared converter code changed')
    driver = Path(protocol['frozen_driver'])
    if digest(driver) != protocol['frozen_driver_sha256']:
        raise ValueError('Frozen dispatch driver changed')
    if digest(driver.parent.parent/'relational_gap/provider.py') != protocol['provider_sha256']:
        raise ValueError('Frozen provider code changed')
    for row in ready['records']:
        directory = output/row['case']
        expected = [str(driver.parent.parent/'.venv/bin/python'), str(driver), 'complete',
                    '--input', str(directory/'request.json'), '--output', str(directory/'completion')]
        if row['command'] != expected or row['request'] != str(directory/'request.json'):
            raise ValueError('Prepared command is not the fixed singleton driver')
        for path, checksum in ((Path(row['request']), row['request_sha256']),
                               (directory/'wire_preview.json', row['wire_preview_sha256'])):
            if digest(path) != checksum:
                raise ValueError('Prepared request changed')
        request, wire = read(row['request']), read(directory/'wire_preview.json')
        if wire['messages'] != [dict(role='system', content=request['system']),
                                dict(role='user', content=request['prompt'])]:
            raise ValueError('Prepared wire does not match the prepared messages')
    return protocol, ready['records']


def run(output):
    output = Path(output).resolve()
    protocol, records = verified_records(output)
    code = digest(Path(__file__))
    execution = dict(ready_sha256=digest(output/'ready.json'), driver_sha256=code,
                     max_new_requests=len(records), workers=1, retries=0)
    receipt = output/'execution_protocol.json'
    if receipt.exists() and read(receipt) != execution:
        raise ValueError('Recorded execution protocol changed')
    write(receipt, execution)
    results = []
    for row in records:
        directory = output/row['case']
        completion = directory/'completion'
        if completion.exists():
            manifest_path = completion/'manifest.json'
            if not manifest_path.exists() or read(manifest_path).get('status') not in TERMINAL_STATUSES:
                raise ValueError('Audit unfinished provider attempt before resuming; no automatic retry')
            previous_result = directory/'execution_result.json'
            returncode = read(previous_result).get('driver_returncode') if previous_result.exists() else None
        else:
            process = subprocess.run(row['command'], cwd=Path(protocol['frozen_driver']).parent.parent,
                                     capture_output=True, text=True)
            (directory/'driver.stdout').write_text(process.stdout)
            (directory/'driver.stderr').write_text(process.stderr)
            returncode = process.returncode
        wire_path = completion/'request.json'
        if wire_path.exists() and read(wire_path) != read(directory/'wire_preview.json'):
            raise ValueError('Actual provider wire differs from the fixed comparison')
        manifest_path = completion/'manifest.json'
        manifest = read(manifest_path) if manifest_path.exists() else {}
        if wire_path.exists() and digest(wire_path) != manifest.get('request_sha256'):
            raise ValueError('Actual provider wire does not match its recorded request hash')
        if manifest.get('status') == 'complete' and not wire_path.exists():
            raise ValueError('Complete provider attempt has no actual request wire')
        result = dict(case=row['case'], candidate_id=row['candidate_id'], request=row['request'],
            request_sha256=row['request_sha256'], completion=str(completion),
            status=manifest.get('status', 'missing_manifest'), driver_returncode=returncode,
            usage=manifest.get('usage'), wire_matches_preview=wire_path.exists(),
            validation_present=(completion/'validation.json').exists())
        write(directory/'execution_result.json', result)
        results.append(result)
        write(output/'execution_results.json', results)
        print(row['case']+' '+result['status'], flush=True)
        if result['status'] not in TERMINAL_STATUSES:
            raise ValueError('Provider did not finish; audit the recorded attempt before continuing')
    write(output/'execution_complete.json', dict(cases=len(results),
        complete=sum(row['status']=='complete' for row in results),
        with_validation=sum(row['status']=='complete' and row['validation_present'] for row in results),
        execution_protocol=execution))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    run(parser.parse_args().input)
