"""Separate larger-output-budget retry of incomplete requests; no input changes."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
from scripts.run_augmentation_diagnostic6 import RUN,read,write,receipt
from augmentation.provider import dispatch
from augmentation.pipeline import parse_response

OUT=RUN/'budget_recovery'


def one(cid,arm,rn):
    original=RUN/'cases'/cid/arm/f'round{rn}'
    directory=OUT/'cases'/cid/arm/f'round{rn}'
    if (directory/'result.json').exists():return read(directory/'result.json')
    old=read(original/'request.json')
    req={'id':read(RUN/'cases'/cid/f'input_{"C" if arm=="D" else arm}.json')['id'],
         'system':old['messages'][0]['content'],'prompt':old['messages'][1]['content'],
         'thinking':'enabled','reasoning_effort':old['reasoning_effort'],'max_tokens':65536}
    manifest=dispatch(req,directory,root=ROOT)
    new=read(directory/'request.json')
    assert {k:v for k,v in old.items() if k!='max_tokens'}=={k:v for k,v in new.items() if k!='max_tokens'}
    result={'case':cid,'arm':arm,'round':rn,'status':'provider_error','provider_status':manifest['status'],
            'original_request':receipt(original/'request.json'),'max_tokens':65536,
            'primary_comparison':False,'response_model':manifest.get('response_model'),'usage':manifest.get('usage')}
    if manifest['status']=='complete':
        try:
            assessment=parse_response((directory/'completion.txt').read_text(),read(RUN/'cases'/cid/'prepared_B.json'),req['id'])
            write(directory/'assessment.json',assessment);result.update(status='decoded',decision=assessment['decision'])
        except (ValueError,TypeError,KeyError) as exc:result.update(status='invalid_response',error=str(exc))
    write(directory/'result.json',result)
    return {k:v for k,v in result.items() if k!='usage'}


def main():
    jobs=[]
    for p in sorted(RUN.glob('cases/*/*/round*/manifest.json')):
        m=read(p)
        if m.get('status')=='incomplete' and m.get('finish_reason')=='length':
            r=read(p.with_name('result.json'));jobs.append((r['case'],r['arm'],r['round']))
    write(OUT/'protocol.json',{'jobs':jobs,'change':'max_tokens 32768 -> 65536 only',
          'all_other_request_fields_unchanged':True,'included_in_primary_comparison':False,
          'purpose':'Distinguish failure to produce a final response from a semantic miss'})
    write(OUT/'cases.json',read(RUN/'cases.json'))
    with ThreadPoolExecutor(max_workers=3) as pool:
        for f in as_completed([pool.submit(one,*j) for j in jobs]):print(json.dumps(f.result(),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
