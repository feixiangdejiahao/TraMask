"""Emit every TypeScript parent from a frozen all-trial prefix cohort.

Select original whole-program fallbacks by source language only. Do not read
prefix runtime outcomes, admission decisions or evaluation annotations.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from relation_search.checkpoint import read
from scripts.run_contract_repair_search import write,frozen,verify
from scripts.run_type_projection_component import emit


def prepare(prefixes,output):
    output.mkdir(parents=True,exist_ok=False);verify(read(prefixes/'seal.json'));p=read(prefixes/'prepared.json');items=[];corpora={}
    for index,item in enumerate(p['items']):
        receipt=item['source_inputs']['corpus'];path=receipt['path']
        if path not in corpora:verify(receipt);corpora[path]=read(path)
        if corpora[path]['language']!='typescript':continue
        candidates=[row for row in item['programs'] if row['is_original']]
        if len(candidates)!=1:raise ValueError('One original whole-program fallback required')
        program=candidates[0]['program'];verify(program)
        for receipt in item['source_inputs'].values():verify(receipt)
        target=output/'cases'/item['case']/f'candidate_{index+1:04d}'/'native'
        artifact=emit(read(program['path']),Path(item['source']),target,dict(timeout=180))
        items.append(dict(case=item['case'],source_parent=item['name'],program=program,artifact=frozen(artifact/'manifest.json'),source_inputs=item['source_inputs']))
    write(output/'cohort.json',dict(version='all-typed-source-parents.v1',prefix_protocol=frozen(prefixes/'prepared.json'),items=items,
        selection='All original whole-program fallback candidates whose source language is TypeScript.',
        native_outcomes_read=False,evaluation_labels_read=False,subject_test_execution=False,external_model_calls=0))
    return dict(programs=len(items),cohort=frozen(output/'cohort.json'))


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--prefixes',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(prepare(a.prefixes,a.output)))
