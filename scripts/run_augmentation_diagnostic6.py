"""Paired material/condition/feedback diagnostic. Frozen pilot inputs remain unchanged.

Selection is informed by prior diagnosis. Generation reads public artifacts only.
Reference patches and benchmark tests are never generation or feedback inputs.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from augmentation.pipeline import build_request, parse_response
from augmentation.provider import dispatch
from augmentation.history import public_trajectory
from anchor_retrieval.syntax import Source, walk, child, is_test_path, units
from scripts.run_augmentation_pilot30 import RUN as OLD, read, write, receipt

RUN = ROOT / 'experiments/relation_distinction/results/diagnostic6_20261008_v1'
ANCHORS = {
    'T10': '598535bed792c443c090', 'T13': '065e6adac82c82d5cd66',
    'T17': 'b7635a1db0374eb565b2', 'T20': 'f6c0fcf8ae4e8d8f623f',
    'T24': 'f3f82ae392c9689d29ab', 'T28': '4585ba218a3c060dff8e',
}
# Manual locations, not expected answers or generated counterexamples.
# Empty ranges mean the complete original file. No gold files are read here.
MATERIAL = {
 'T10': {
  'bandit/cli/main.py': [[390,455],[625,885]],
  'bandit/core/manager.py': [], 'bandit/formatters/json.py': [],
  'tests/unit/cli/test_main.py': [], 'tests/unit/core/test_manager_cache.py': [],
 },
 'T13': {
  'script.go': [[200,370]], 'objects.go': [[570,780],[1450,1510]],
  'compiled_function_call_test.go': [], 'script_test.go': [[1,45],[620,715]],
 },
 'T17': {
  'compiler.go': [[680,720],[815,965]], 'vm.go': [[335,410]],
  'objects.go': [[215,265],[870,910],[935,970],[1235,1280],[1510,1580]],
  'destructuring_test.go': [], 'vm_test.go': [[1,100]],
 },
 'T20': {
  'pkg/kgateway/extensions2/plugins/trafficpolicy/consistent_hash.go': [],
  'pkg/kgateway/extensions2/plugins/trafficpolicy/consistent_hash_test.go': [],
  'install/helm/kgateway-crds/templates/gateway.kgateway.dev_trafficpolicies.yaml': [[350,535]],
 },
 'T24': {
  'src/schema/actions/zodSchemer/parser/item.ts': [],
  'src/schema/actions/zodSchemer/parser/map.ts': [],
  'src/schema/actions/zodSchemer/parser/utils.ts': [],
  'src/schema/actions/zodSchemer/parser/item.unit.test.ts': [],
  'src/schema/actions/zodSchemer/parser/map.unit.test.ts': [],
  'src/schema/actions/requiredIf.unit.test.ts': [],
 },
 'T28': {
  'packages/query-core/src/query.ts': [[50,110],[285,365],[490,765],[790,920]],
  'packages/query-core/src/queryObserver.ts': [[70,135],[440,490],[740,825]],
  'packages/query-persist-client-core/src/createPersister.ts': [],
  'packages/query-core/src/__tests__/persisterRestoreResult.test.tsx': [],
  'packages/react-query/src/__tests__/fine-grained-persister.test.tsx': [],
 },
}


def selected_line(line, ranges):
    return not ranges or any(a <= line <= b for a, b in ranges)


def snippets(code, ranges):
    lines = code.splitlines()
    return [{'start_line': a, 'end_line': min(b, len(lines)),
             'code': '\n'.join(lines[a-1:b])} for a, b in (ranges or [[1,len(lines)]])]


def extract_facts(repository, material, language):
    """Generic syntax facts on selected regions; no case IDs or target labels."""
    facts = []
    for path, ranges in material.items():
        code = (repository / path).read_text()
        if is_test_path(path):
            continue
        if path.endswith(('.yaml','.yml')):
            stack = []
            for number, line in enumerate(code.splitlines(), 1):
                m = re.match(r'^(\s*)([\w-]+):\s*(.*)$', line)
                if not m: continue
                indent, key, value = len(m[1]), m[2], m[3]
                while stack and stack[-1][0] >= indent: stack.pop()
                stack.append((indent,key))
                if selected_line(number,ranges) and key in {'pattern','enum','type','x-kubernetes-list-type','x-kubernetes-list-map-keys'}:
                    facts.append({'kind':'declarative_constraint','path':path,'line':number,
                                  'field_path':'.'.join(x[1] for x in stack), 'value':value})
            continue
        source = Source(path, code, language)
        per_file = []
        for n in walk(source.root):
            line = n.start_point.row + 1
            if not selected_line(line,ranges): continue
            if n.type in {'if_statement','conditional_expression','ternary_expression'}:
                cond = child(n,'condition')
                if cond is None: continue
                parent=n.parent
                while parent and parent.type not in {'function_definition','function_declaration','method_declaration','method_definition','arrow_function'}:
                    parent=parent.parent
                name=source.text(child(parent,'name')) if parent else ''
                exits=[{'line':x.start_point.row+1,'code':source.text(x)[:220]} for x in walk(n)
                       if x.type in {'return_statement','throw_statement','raise_statement'}
                       or x.type in {'call','call_expression'} and re.search(r'(?:^|\.)(?:exit|Exit|panic)\s*\(',source.text(x))]
                per_file.append({'kind':'branch','path':path,'line':line,'function':name,
                                 'condition':source.text(cond),'body':source.text(n)[:850], 'terminations':exits[:5]})
            elif n.type in {'assignment_statement','short_var_declaration','assignment','lexical_declaration'}:
                t=source.text(n)
                if len(t)<550 and (re.search(r'\b(?:nil|null|undefined|UndefinedValue|make|new)\b|\?\?|\|\||\[|\{',t)):
                    per_file.append({'kind':'state_or_default_expression','path':path,'line':line,'code':t})
        # All selected branches are retained. The report records scope selection.
        facts.extend(per_file)
    return {'method':'tree-sitter branch/default/state syntax plus YAML constraint paths',
            'scope':'automatic extraction within manually selected source regions',
            'semantics':'Facts show implementation predicates and expressions, not required behavior or proven coverage.',
            'facts':facts}


def selected_history(case, paths):
    document=public_trajectory(read(case['trajectory']))
    hits=[]; validations=[]
    for ordinal, step in enumerate(document['steps']):
        commands='\n'.join(c['arguments'].get('command','') for c in step.get('tool_calls',[]) if isinstance(c['arguments'].get('command',''),str))
        if not commands: continue
        if any(p in commands for p in paths): hits.append(ordinal)
        if re.search(r'\bgo\s+test\b|\bpytest\b|\bvitest\b|\bpnpm\b.*\btest', commands): validations.append(ordinal)
    # Reproducible selection within manually nominated files; not hidden reasoning.
    selected=sorted(set(hits[-12:] + validations[-3:]))
    return [{'ordinal':i,'step':document['steps'][i],
             'selection':'last file-related commands and last three validation commands',
             'execution_status':'command and observed feedback; final-version execution not inferred'} for i in selected]


def prepare():
    if (RUN/'protocol.json').exists(): return read(RUN/'protocol.json')
    cases=[c for c in read(OLD/'cases.json') if c['id'] in ANCHORS]
    write(RUN/'cases.json',cases)
    comparisons=[]
    for case in cases:
        cid=case['id']; repository=Path(case['repository']); directory=RUN/'cases'/cid
        original=read(OLD/'cases'/cid/'prepared.json')
        candidate=next(c for c in original['candidates'] if ANCHORS[cid] in c['id'])
        original_request=read(OLD/'cases'/cid/'generation'/candidate['id']/'request.json')
        a_request={'id':candidate['id'],'system':original_request['messages'][0]['content'],
                   'prompt':original_request['messages'][1]['content'],'thinking':'enabled',
                   'reasoning_effort':'high','max_tokens':32768}
        # Same candidate reason, contrast, relations, and system message in A/B/C.
        # B replaces material locations, actual related tests, and history only.
        b=deepcopy(original); bc=deepcopy(candidate)
        material=MATERIAL[cid]
        bc['source_paths']=list(material)
        bc['test_ids']=[tid for tid,t in original['tests'].items()
                        if t['origin']=='repository' and t['span']['path'] in material
                        and selected_line(t['span']['line'],material[t['span']['path']])]
        bc['trajectory']=selected_history(case,material)
        b['candidates']=[bc]
        for path,ranges in material.items():
            code=(repository/path).read_text()
            b['source_files'][path]={'language':'yaml' if path.endswith('.yaml') else case['language'],
                'origin':'repository','sha256':hashlib.sha256(code.encode()).hexdigest(),
                'excerpts':snippets(code,ranges), 'selection':'manual source-region selection for diagnosis'}
        b_request=build_request(b,candidate['id']); b_request.update(max_tokens=32768,reasoning_effort='high')
        facts=extract_facts(repository,material,case['language'])
        payload=json.loads(b_request['prompt']);payload['program_extracted_conditions']=facts
        c_request={**b_request,'prompt':json.dumps(payload,ensure_ascii=True)}
        write(directory/'prepared_A.json',original)
        write(directory/'prepared_B.json',b)
        write(directory/'conditions.json',facts)
        for arm,req in [('A',a_request),('B',b_request),('C',c_request)]: write(directory/f'input_{arm}.json',req)
        ap=json.loads(a_request['prompt'])
        btest=set(bc['test_ids']); atest=set(candidate['test_ids'])
        comparisons.append({'case':cid,'anchor':candidate['id'],
            'selection_note':'Anchor chosen after prior diagnosis; A is a matched original-input control, not a fresh full automatic search.',
            'original_candidate':{k:candidate[k] for k in ['family','reason','contrast','function_ids']},
            'original_files':candidate['source_paths'],'manual_regions':material,
            'added_files':sorted(set(material)-set(candidate['source_paths'])),
            'removed_files':sorted(set(candidate['source_paths'])-set(material)),
            'original_test_count':len(atest),'manual_test_count':len(btest),
            'added_test_ids':sorted(btest-atest),'removed_test_ids':sorted(atest-btest),
            'original_history_steps':[x['step']['step_id'] for x in candidate['trajectory']],
            'manual_history_steps':[x['step']['step_id'] for x in bc['trajectory']],
            'request_bytes':{a:len(req['prompt'].encode()) for a,req in [('A',a_request),('B',b_request),('C',c_request)]},
            'fact_count':len(facts['facts']),
            'manual_content_already_in_original':{p:{
                'in_source_files':p in ap['current_or_historical_sources'],
                'in_submitted_patch':p in ap['submitted_patch'],
                'excerpt_verbatim_in_whole_payload':[x['code'] in a_request['prompt'] or x['code'] in json.dumps(ap,ensure_ascii=False) for x in snippets((repository/p).read_text(),ranges)]
                } for p,ranges in material.items()},
            'original_request':receipt(OLD/'cases'/cid/'generation'/candidate['id']/'request.json'),
            'material_receipts':[receipt(repository/p) for p in material]})
    write(RUN/'material_comparison.json',comparisons)
    protocol={'created_at':datetime.now(timezone.utc).isoformat(), 'cases':list(ANCHORS),
      'primary_targets':{'T10':['T10-R1'],'T13':['T13-R1'],'T17':['T17-R1'],'T20':['T20-G1','T20-G2'],'T24':['T24-R1'],'T28':['T28-R1']},
      'secondary_target':'T24-G2 recorded separately if spontaneously found',
      'arms':{'A':'Original saved input, then self-review without execution feedback',
              'B':'Same hypothesis/system, manually selected public materials, then self-review',
              'C':'B plus automatically extracted syntax conditions, then self-review',
              'D':'Shares C round 1; second call receives actual original-patch execution feedback'},
      'calls_per_arm_case':2,'unique_planned_calls':42,'shared_call':'C/D round 1 identical outcome reused to isolate feedback',
      'model':'deepseek-v4-flash','temperature':0,'max_tokens':32768,'reasoning_effort':'high',
      'generation_excludes':['gold patch','benchmark tests','benchmark failure feedback','manual expected counterexamples'],
      'manual_selection_informed_by_previous_diagnosis':True,
      'condition_extraction_scope':'manual regions; not claimed to be fully automatic localization',
      'original_full_run':'Use frozen 30-trial report separately; A here is a selected-input comparison.',
      'execution':'Fresh network-isolated original benchmark containers; no production edits; same framework per case.',
      'feedback':'Original-patch results only. No gold outcomes or evaluator target labels.',
      'evaluation':'Separate exact target detection, executable tests, semantic bug witness, dynamic gold pair if portable, and wrong-oracle claims.',
      'source':receipt(Path(__file__))}
    write(RUN/'protocol.json',protocol)
    return protocol


def base_request(cid,arm): return read(RUN/'cases'/cid/f'input_{"C" if arm=="D" else arm}.json')


def run_one(cid,arm,round_number):
    directory=RUN/'cases'/cid/arm/f'round{round_number}'
    if (directory/'result.json').exists(): return read(directory/'result.json')
    req=base_request(cid,arm)
    if round_number==2:
        prior_dir=RUN/'cases'/cid/('C' if arm=='D' else arm)/'round1'
        if not (prior_dir/'result.json').exists(): raise ValueError('first_round_pending')
        prior=(prior_dir/'completion.txt').read_text() if (prior_dir/'completion.txt').exists() else ''
        followup={'previous_response':prior,
                  'instruction':'Reassess your previous response against the supplied public requirement and source. Return a complete replacement JSON response. You may retain, refine, or reject the claim. Keep correct existing assertions. Do not treat implementation output as the oracle. If you generate tests, keep the original test naming/framework conventions and legal module scope.'}
        if arm=='D':
            execution=prior_dir/'execution/feedback.json'
            if not execution.exists(): raise ValueError('execution_feedback_pending')
            followup['observed_execution']=read(execution)
            followup['feedback_instruction']='Use observed failures to repair test construction or refine the hypothesis. Passing tests alone do not prove all related conditions were exercised. Do not change a requirement-supported expectation just to make a test pass.'
        else: followup['observed_execution']='Withheld in this control; perform self-review without runtime feedback.'
        req['prompt']+='\n\nSECOND_REVIEW\n'+json.dumps(followup,ensure_ascii=True)
    if directory.exists(): raise RuntimeError('unfinished_dispatch_requires_review:'+str(directory))
    manifest=dispatch(req,directory,root=ROOT)
    result={'case':cid,'arm':arm,'round':round_number,'provider_status':manifest['status'],
            'response_model':manifest.get('response_model'),'usage':manifest.get('usage'), 'status':'provider_error'}
    if manifest['status']=='complete':
        try:
            prepared=read(RUN/'cases'/cid/f'prepared_{"A" if arm=="A" else "B"}.json')
            assessment=parse_response((directory/'completion.txt').read_text(),prepared,req['id'])
            write(directory/'assessment.json',assessment)
            result.update(status='decoded',decision=assessment['decision'],test_files=len(assessment['tests']))
        except (ValueError,TypeError,KeyError) as exc:
            result.update(status='invalid_response',error=str(exc))
    write(directory/'result.json',result)
    return result


def execute_one(cid,arm,round_number):
    from combination_testing.runner import freeze_artifact,run_artifact
    from generic_composition.runner import infer_harness
    from scripts.execute_relational_gap_v7 import python_source_environment
    case=next(c for c in read(RUN/'cases.json') if c['id']==cid)
    directory=RUN/'cases'/cid/arm/f'round{round_number}'
    output=directory/'execution'
    if (output/'feedback.json').exists(): return read(output/'feedback.json')
    output.mkdir(parents=True,exist_ok=True)
    summary={'case':cid,'arm':arm,'round':round_number,'status':'not_executed','gold_used':False}
    ap=directory/'assessment.json'
    if not ap.exists() or read(ap)['decision']!='gap':
        summary['reason']='No accepted generated test in the first response; there is no runtime evidence.'
        write(output/'feedback.json',summary);return summary
    row=read(ap);repository=Path(case['repository']);files={};names=[]
    try:
        for edit in row['tests']:
            target=repository/edit['path']
            files[edit['path']]=(target.read_text()+'\n\n' if edit['mode']=='append' else '')+edit['code']+'\n'
            names.extend(u.name for u in units(Source(edit['path'],edit['code'],case['language']))[0] if u.test)
        names=sorted(set(names))
        if not names: raise ValueError('no_named_generated_tests')
        selector=' or '.join(names) if case['language']=='python' else '('+'|'.join(re.escape(n) for n in names)+')'
        harness=infer_harness(repository,case['language'],list(files),python='python',name_filter=selector)
        command=harness['command']
        if case['language']=='python': command=python_source_environment(repository)['command']+command
        if case['language']=='go': command=command.replace('go test ','go test -coverprofile="$COMBINATION_REPORT_DIR/coverage.out" ',1)
        files.update(harness.get('files',{}))
        artifact=output/'artifact'
        if not artifact.exists(): freeze_artifact(artifact,cid,files,command,harness['report_format'],harness['report_path'],timeout=300,
            metadata={'assessment':receipt(ap),'generated_test_names':names,'source_mode':'unmodified_model_output'})
        case['base_commit']=read(OLD/'cases'/cid/'repository_provenance.json')['base_commit']
        result_path=output/'candidate/result.json'
        result=read(result_path) if result_path.exists() else run_artifact(artifact,'candidate',output/'candidate',registry=[case])
        logs={}
        for f in ['stdout.txt','stderr.txt','go.jsonl']:
            path=output/'candidate'/f
            if path.exists(): logs[f]=path.read_text(errors='replace')[-18000:]
        summary.update(status=result['status'],tests=result['tests'],errors=result.get('errors',[]),
                       process=result.get('process',{}),generated_test_names=names,logs=logs,
                       trigger_coverage='Runtime test outcomes available; target-condition activation is not inferred from pass alone.')
    except Exception as exc:
        summary.update(status='execution_setup_error',error_type=type(exc).__name__,error=str(exc))
    write(output/'feedback.json',summary)
    return {k:v for k,v in summary.items() if k not in ['logs','tests']}


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('action',choices=['prepare','generate','execute'])
    p.add_argument('--round',type=int,default=1);p.add_argument('--arm',action='append');p.add_argument('--case',action='append');p.add_argument('--workers',type=int,default=6)
    a=p.parse_args()
    if a.action=='prepare': print(json.dumps(prepare(),ensure_ascii=False,indent=2));return
    cases=a.case or list(ANCHORS);arms=a.arm or ['A','B','C']
    jobs=[(cid,arm,a.round) for cid in cases for arm in arms]
    function=run_one if a.action=='generate' else execute_one
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(function,*j) for j in jobs]):
            row=f.result();print(json.dumps({k:v for k,v in row.items() if k!='usage'},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
