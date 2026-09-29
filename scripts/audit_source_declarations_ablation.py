"""Independently inspect the source-only prompt intervention; no model dispatch."""
from __future__ import annotations
import argparse,copy,hashlib,json
from pathlib import Path

def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(data):return hashlib.sha256(data).hexdigest()
def source_hash(meta):
    values={meta[key] for key in ('source_sha256','sha256') if key in meta}
    assert len(values)==1, 'Missing or conflicting source hash'
    return next(iter(values))
def parse_blocks(text):
    data=text.encode();blocks=[]
    if data==b'No source declarations were retrieved for this candidate.\n':return blocks
    while data:
        header,data=data.split(b'\n',1)
        assert header.startswith(b'SOURCE ')
        meta=json.loads(header[7:]);span=meta['span'];length=span['end_byte']-span['start_byte'];assert length>=0
        code=data[:length];assert len(code)==length and data[length:length+1]==b'\n'
        blocks.append((meta,code));data=data[length+1:]
    return blocks

def audit(root):
    root=Path(root);ready=read(root/'ready.json');stage=read(root/'stage.json');campaign=Path(stage['campaign']);rows=[]
    assert ready['prepared']==ready['expected']==len(stage['cases'])==17
    assert stage['feedback_into_main_campaign'] is False
    assert sha(campaign/'configuration.json')==stage['configuration_sha256']
    for record in ready['records']:
        case=record['case'];old_path=Path(record['treatment_request']);new_path=Path(record['request']);old=read(old_path);new=read(new_path)
        assert sha(old_path)==record['treatment_request_sha256'] and sha(new_path)==record['request_sha256']
        offered=next(iter(old['offered'].values()))['candidate'];assert len(old['offered'])==1 and offered['id']==record['candidate_id']
        inventory=[]
        for p in old_path.parent.glob('request_[0-9][0-9][0-9].json'):
            q=read(p);cid=next(iter(q['offered'].values()))['candidate']['id'];inventory.append((digest(cid.encode()),str(p),cid))
        assert sorted(inventory)[0][2]==record['candidate_id']
        before,after=json.loads(old['prompt']),json.loads(new['prompt']);normalized=copy.deepcopy(after)
        for a,b,c in zip(before['candidates'],after['candidates'],normalized['candidates']):
            assert set(a)==set(b);old_e=a['dependency_evidence'];new_e=b['dependency_evidence'];expected=copy.deepcopy(new_e)
            for k in ['rendered','rendered_bytes','status']:expected[k]=old_e[k]
            assert expected==old_e;c['dependency_evidence']=old_e
        assert normalized==before
        normalized_request=copy.deepcopy(new)
        for k in ['prompt','id']:normalized_request[k]=old[k]
        del normalized_request['source_declarations_ablation'];assert normalized_request==old
        original_wire=read(record['original_wire']);preview=read(root/case/'wire_preview.json')
        assert sha(record['original_wire'])==record['original_wire_sha256'];assert sha(root/case/'wire_preview.json')==record['wire_preview_sha256']
        expected_wire=copy.deepcopy(original_wire);expected_wire['messages'][1]['content']=new['prompt'];assert expected_wire==preview
        corpus_path=Path(old['source_prepared'])/'corpus.json';assert sha(corpus_path)==record['corpus_sha256'];corpus=read(corpus_path)
        versions={(p,digest(x['code'].encode())):x['code'].encode() for p,x in corpus['sources'].items()}
        for item in old['offered'].values():
            candidate=item['candidate'];owner=corpus['tests'][candidate['base_test_id']]['span']['path'];original=corpus['sources'][owner]['code'].encode();data=original
            edits=candidate['program_edits'] if candidate.get('instrumentation',{}).get('status')=='instrumented' else candidate['edits']
            assert not any(e.get('role')=='semantic_expected' for e in candidate['edits']), 'Protocol only covers initial source candidates'
            for e in sorted(edits,key=lambda e:(e['span']['start_byte'],e['span']['end_byte']),reverse=True):
                s=e['span'];assert s['path']==owner and original[s['start_byte']:s['end_byte']].decode()==e['before'];data=data[:s['start_byte']]+e['after'].encode()+data[s['end_byte']:]
            versions[(owner,digest(data))]=data
        declarations=0;emitted=0
        for c in after['candidates']:
            evidence=old['analysis_evidence'][c['candidate']];blocks=parse_blocks(c['dependency_evidence']['rendered']);emitted+=len(blocks)
            for meta,code in blocks:
                span=meta['span'];assert versions[(span['path'],source_hash(meta))][span['start_byte']:span['end_byte']]==code
            for declaration in evidence['declarations']:
                span=declaration['span'];code=declaration['code'].encode();assert versions[(span['path'],declaration['source_sha256'])][span['start_byte']:span['end_byte']]==code
                owners=[(m,b) for m,b in blocks if source_hash(m)==declaration['source_sha256'] and m['span']['path']==span['path'] and m['span']['start_byte']<=span['start_byte']<=span['end_byte']<=m['span']['end_byte']]
                assert owners;assert any(b[span['start_byte']-m['span']['start_byte']:span['end_byte']-m['span']['start_byte']]==code for m,b in owners);declarations+=1
            assert c['dependency_evidence']['rendered_bytes']==len(c['dependency_evidence']['rendered'].encode())
        rows.append(dict(case=case,candidate_id=record['candidate_id'],declarations=declarations,emitted=emitted,original_prompt_bytes=len(old['prompt'].encode()),source_only_prompt_bytes=len(new['prompt'].encode())))
    return dict(role='independent_evaluation_only',audit_code_sha256=sha(__file__),ready_sha256=sha(root/'ready.json'),stage_sha256=sha(root/'stage.json'),cases=rows,total_declarations=sum(r['declarations'] for r in rows),checks=['same SHA-first candidate per case','same complete test/assertions/edits/offered/system and local facts','only rendered source evidence and derived fields changed in prompt','same model settings in prepared wire','independent reconstruction of original and edited source SHA/spans','all complete declarations represented without truncation'],limits=['Prepared inputs only; no completion or semantic outcome was used.','This removes binding, dependence, observation and unknown annotations together; not a graph-edge-only causal intervention.'])

if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--input',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();out=audit(a.input)
    with a.output.open('x') as f:json.dump(out,f,indent=2)
    print(json.dumps({k:v for k,v in out.items() if k!='cases'}))
