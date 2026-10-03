"""Append resolved declaration documentation to a fixed source-only cohort."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search import source_contract_evidence
from relation_search.checkpoint import read,digest
from scripts.run_test_admission import _enrich
from scripts.run_contract_selection import write,frozen


def prepare(source,output):
    output.mkdir(parents=True,exist_ok=False)
    cohort=read(source);entries=[];cache={}
    for i,row in enumerate(cohort['items']):
        if digest(row['request_path'])!=row['request_sha256']:
            raise ValueError('Frozen source request changed')
        paths=tuple(row['source_inputs'][key]['path'] for key in ('corpus','frontend','candidates'))
        if paths not in cache:
            for key in ('corpus','frontend','candidates'):
                receipt=row['source_inputs'][key]
                if digest(receipt['path'])!=receipt['sha256']:
                    raise ValueError('Frozen source input changed')
            corpus,frontend,candidates=(read(path) for path in paths)
            if isinstance(candidates,dict):candidates=candidates['candidates']
            corpus,_=_enrich(corpus,frontend,{c['id']:c for c in candidates},paths[0],output,i)
            cache[paths]=corpus
        analysis=read(row['analysis_path'])['analysis']
        evidence=source_contract_evidence.collect(cache[paths],analysis)
        request=read(row['request_path']);payload=json.loads(request['prompt'])
        payload['api_contract_context']=evidence
        request['prompt']=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
        request['prompt_bytes']=len(request['system'].encode())+len(request['prompt'].encode())
        request['id']=request['query_sha256']=hashlib.sha256(json.dumps(
            {k:request[k] for k in ('system','prompt','thinking','max_tokens')},
            sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        directory=output/f'item_{i:04d}'
        write(directory/'evidence.json',evidence);write(directory/'request.json',request)
        item=copy.deepcopy(row)
        item.update(request_path=str((directory/'request.json').resolve()),
                    request_sha256=digest(directory/'request.json'),
                    parent_request=frozen(row['request_path']),
                    api_records=len(evidence['records']),unknowns=len(evidence['unknowns']))
        entries.append(item)
        print(json.dumps(dict(case=row['case'],records=item['api_records'],
                              unknowns=item['unknowns'],bytes=request['prompt_bytes'])),flush=True)
    manifest=dict(method='compact',items=entries,source=frozen(source),
        augmentation=frozen(source_contract_evidence.__file__),builder=frozen(__file__),
        evaluation_metadata_not_sent_to_provider=True)
    write(output/'cohort.json',manifest)
    return dict(items=len(entries),with_documentation=sum(bool(r['api_records']) for r in entries))


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(prepare(args.input,args.output)))
