"""Recover syntax/optional-reference transport only; never edit generated tests."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from augmentation.pipeline import parse_response
from scripts.run_augmentation_diagnostic6 import RUN,base_request,read,write


def strip_trailing_commas(text):
    result=[]; quoted=False; escaped=False
    for index,char in enumerate(text):
        if quoted:
            result.append(char)
            if escaped: escaped=False
            elif char=='\\': escaped=True
            elif char=='"': quoted=False
        elif char=='"': quoted=True;result.append(char)
        elif char==',' and text[index+1:].lstrip().startswith((']', '}')): continue
        else: result.append(char)
    return ''.join(result)


def main():
    paths=[*RUN.glob('cases/*/*/round*/result.json'), *(RUN/'budget_recovery').glob('cases/*/*/round*/result.json')]
    for path in sorted(paths):
        directory=path.parent
        if (directory/'assessment.json').exists(): continue
        result=read(path)
        if result['status']!='invalid_response':continue
        cid,arm=result['case'],result['arm']
        prepared=read(RUN/'cases'/cid/f'prepared_{"A" if arm=="A" else "B"}.json')
        candidate_id=base_request(cid,arm)['id']
        raw=(directory/'completion.txt').read_text()
        try:
            normalized=strip_trailing_commas(raw)
            data=json.loads(normalized)
            before=json.dumps(data['tests'],ensure_ascii=False,sort_keys=True)
            removed=[]
            if data['decision']!='selection_problem':
                allowed=set(next(c for c in prepared['candidates'] if c['id']==candidate_id)['test_ids'])
                removed=[x for x in data['existing_test_ids'] if x not in allowed]
                data['existing_test_ids']=[x for x in data['existing_test_ids'] if x in allowed]
            assessment=parse_response(json.dumps(data),prepared,candidate_id)
            assert before==json.dumps(assessment['tests'],ensure_ascii=False,sort_keys=True)
            write(directory/'transport_recovery.json',{
                'original_result_status':result['status'],'original_error':result.get('error'),
                'removed_trailing_commas':normalized!=raw,'removed_optional_test_references':removed,
                'generated_tests_unchanged_sha256':hashlib.sha256(before.encode()).hexdigest(),
                'semantic_edits':False,'new_model_calls':0,
                'scope':'uniform transport recovery; report separately from original acceptance'})
            write(directory/'assessment.json',assessment)
            print(cid,arm,result['round'],assessment['decision'],'transport recovered',flush=True)
        except (ValueError,TypeError,KeyError):
            print(cid,arm,result['round'],'not recoverable by transport-only rules',flush=True)


if __name__=='__main__':main()
