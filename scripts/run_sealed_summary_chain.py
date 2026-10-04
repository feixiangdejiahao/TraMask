"""Compose complete sealed summaries without revalidating their execution.

The component spec is a JSON list in precedence order. Each component declares
JSON pointers into its sealed prepared/summary documents. Source rows can be an
array (including repeated attempts) or an object keyed by case. This script
reads no audit artifact and dispatches neither providers nor subject programs.

Required component fields: name, commit, prepared_version, summary_version,
prepared, summary, prepared_seal, summary_seal, prepared_cases, source_rows,
summary_rows, summary_denominator_pointer, declared_alert_count_pointer,
alert_rows_pointer, summary_prepared_pointer. A seal is {receipt, pointer}; the
pointer selects the complete prepared/summary receipt inside that seal. A row
selector is {pointer, kind, case_pointer}, with kind=array or object. Object
keys supply the case when case_pointer=null; array strings use case_pointer="".
source_rows adds inputs: all five canonical roles map to a pointer or null.
corpus.json/frontend.json/issue.md are mandatory. summary_rows adds alert_pointer.
Optional alert_rows_pointer selects the summary's full declared alert rows.
For example, a repeated attempt source uses case_pointer=/selection/case and
inputs corpus.json=/source_inputs/corpus, frontend.json=/source_inputs/frontend,
issue.md=/issue, with null case.json/selection.json.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'sealed-complete-summary-chain.v1'
REQUIRED_INPUTS = {'corpus.json', 'frontend.json', 'issue.md'}
INPUTS = REQUIRED_INPUTS | {'case.json', 'selection.json'}
POLICY = {
    'selection': 'Copy the first non-null complete alert in the frozen component order for every original trial.',
    'scope': 'Validate sealed document bytes, declared complete row projections, common source bytes and exact alert identity.',
    'source_identity': 'Every trial shares corpus/frontend/issue SHA256; any overlapping case/selection metadata must also have equal SHA256. Verify every declared source file.',
    'code_commit': 'Verify that each declared full immutable commit exists. The commit is recorded provenance, not a verification of the component algorithm closure.',
    'underlying_execution': 'Delegate provider/native provenance and semantic validity to separately identified component evidence. Do not open those audit artifacts here.',
    'provider_native_receipts_revalidated': False,
    'algorithm_execution_closures_revalidated': False,
    'evaluation_labels_used': False,
    'cost': 'This composition makes zero fresh provider calls and zero native executions. It does not infer a cold-run cost from historical summaries.',
}
COMPONENT_FIELDS = {
    'name', 'commit', 'prepared_version', 'summary_version', 'prepared', 'summary',
    'prepared_seal', 'summary_seal', 'prepared_cases', 'source_rows', 'summary_rows',
    'summary_denominator_pointer', 'declared_alert_count_pointer', 'alert_rows_pointer',
    'summary_prepared_pointer',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, 'Duplicate JSON object key: ' + key)
        value[key] = item
    return value


def read(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def frozen(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=digest(path.read_bytes()))


def canonical(value):
    return digest(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode())


def pointer(document, path):
    require(isinstance(path,str) and (path == '' or path.startswith('/')), 'Invalid JSON pointer')
    current = document
    if not path:
        return current
    for raw in path[1:].split('/'):
        require(not re.search(r'~(?![01])',raw), 'Invalid JSON pointer escape')
        key = raw.replace('~1','/').replace('~0','~')
        require('audit' not in key.lower(), 'Audit fields cannot be projection inputs')
        if isinstance(current,dict):
            require(key in current, 'Missing JSON pointer: ' + path)
            current = current[key]
        elif isinstance(current,list):
            require(re.fullmatch(r'0|[1-9][0-9]*',key) is not None and int(key)<len(current), 'Invalid array JSON pointer: ' + path)
            current = current[int(key)]
        else:
            raise ValueError('JSON pointer traverses a scalar: ' + path)
    return current


def escape_pointer(value):
    return value.replace('~','~0').replace('/','~1')


def rows(document, selector, *, extras=()):
    require(isinstance(selector,dict) and set(selector)=={'pointer','kind','case_pointer'}|set(extras), 'Unknown row selector fields')
    value = pointer(document,selector['pointer'])
    require(selector['kind'] in {'array','object'}, 'Unknown row collection kind')
    if selector['kind']=='array':
        require(isinstance(value,list) and isinstance(selector['case_pointer'],str), 'Expected array row collection')
        items = enumerate(value)
    else:
        require(isinstance(value,dict), 'Expected keyed row collection')
        require(selector['case_pointer'] is None, 'Keyed rows must use object keys as cases')
        items = value.items()
    result = []
    for key,row in items:
        case = key if selector['kind']=='object' else pointer(row,selector['case_pointer'])
        require(isinstance(case,str) and bool(case), 'Missing string trial identity')
        location = selector['pointer']+'/'+escape_pointer(str(key))
        result.append(dict(case=case,row=row,pointer=location))
    return result


def complete_index(records, expected=None):
    index = {}
    for row in records:
        require(row['case'] not in index, 'Duplicate complete trial row: '+row['case'])
        index[row['case']] = row
    require(bool(index), 'Empty complete trial cohort')
    if expected is not None:
        require(set(index)==set(expected), 'Complete trial cohort differs')
    return index


class Verifier:
    def __init__(self):
        self.checked = {}
        self.commits = set()

    def receipt(self, receipt):
        require(isinstance(receipt,dict) and set(receipt)=={'path','sha256'}, 'Malformed file receipt')
        require(isinstance(receipt['path'],str) and Path(receipt['path']).is_absolute(), 'Receipt path must be absolute')
        require(isinstance(receipt['sha256'],str) and re.fullmatch('[0-9a-f]{64}',receipt['sha256']) is not None, 'Malformed SHA256')
        path = Path(receipt['path']).resolve()
        if path not in self.checked:
            require(path.is_file(), 'Missing sealed data file: '+str(path))
            self.checked[path] = digest(path.read_bytes())
        require(self.checked[path]==receipt['sha256'], 'Changed sealed data file: '+str(path))
        return path

    def document(self, receipt):
        value = read(self.receipt(receipt))
        require(isinstance(value,dict), 'Component document must be an object')
        require(value.get('evaluator_only') is not True and 'audit' not in str(value.get('version','')).lower(), 'Audit artifacts cannot be components')
        return value

    def seal(self, declaration, target):
        require(isinstance(declaration,dict) and set(declaration)=={'receipt','pointer'}, 'Malformed seal declaration')
        seal = read(self.receipt(declaration['receipt']))
        require(pointer(seal,declaration['pointer'])==target, 'Seal identifies a different document')

    def commit(self, commit):
        require(isinstance(commit,str) and re.fullmatch('[0-9a-f]{40}',commit) is not None, 'Require full immutable code commit')
        if commit in self.commits:
            return
        try:
            kind=subprocess.check_output(['git','-C',str(ROOT),'cat-file','-t',commit],stderr=subprocess.PIPE).decode().strip()
        except subprocess.CalledProcessError as exc:
            raise ValueError('Declared code commit is unavailable') from exc
        require(kind=='commit','Declared code object is not a commit')
        self.commits.add(commit)


def component(spec, verifier):
    require(isinstance(spec,dict) and set(spec)==COMPONENT_FIELDS, 'Unknown or missing component declaration fields')
    require(isinstance(spec['name'],str) and bool(spec['name']), 'Missing component name')
    require(all(isinstance(spec[k],str) and spec[k] for k in ('prepared_version','summary_version')), 'Missing declared component versions')
    verifier.commit(spec['commit'])
    prepared = verifier.document(spec['prepared']);summary = verifier.document(spec['summary'])
    verifier.seal(spec['prepared_seal'],spec['prepared'])
    verifier.seal(spec['summary_seal'],spec['summary'])
    require(prepared.get('version')==spec['prepared_version'] and summary.get('version')==spec['summary_version'], 'Declared component version differs')
    # A summary seal is mandatory. When the source format declares a stage, it
    # must also name a completed stage; unknown stage names are not inferred.
    if 'stage' in summary:
        require(summary['stage']=='complete','Component summary is not complete')
    if spec['summary_prepared_pointer'] is not None:
        require(pointer(summary,spec['summary_prepared_pointer'])==spec['prepared'], 'Summary identifies different prepared bytes')
    cohort = complete_index(rows(prepared,spec['prepared_cases']))
    projected = rows(summary,spec['summary_rows'],extras={'alert_pointer'})
    output = complete_index(projected,cohort)
    count = pointer(summary,spec['summary_denominator_pointer'])
    require(type(count) is int and count==len(cohort), 'Summary denominator differs')
    alert_rows = []
    for item in projected:
        alert = pointer(item['row'],spec['summary_rows']['alert_pointer'])
        require(alert is None or isinstance(alert,dict) and bool(alert), 'Alert must be null or a complete nonempty object')
        item['alert'] = alert
        item['alert_pointer'] = item['pointer']+spec['summary_rows']['alert_pointer']
        if alert is not None:
            alert_rows.append(item['row'])
    declared_count = pointer(summary,spec['declared_alert_count_pointer']) if spec['declared_alert_count_pointer'] is not None else None
    require(spec['declared_alert_count_pointer'] is None or type(declared_count) is int and declared_count==len(alert_rows), 'Declared alert count differs')
    require(spec['declared_alert_count_pointer'] is not None or spec['alert_rows_pointer'] is not None, 'Require a declared alert inventory or count')
    if spec['alert_rows_pointer'] is not None:
        require(pointer(summary,spec['alert_rows_pointer'])==alert_rows, 'Declared complete alert rows differ')
    source_selector = spec['source_rows']
    source_records = rows(prepared,source_selector,extras={'inputs'})
    roles = source_selector['inputs']
    require(isinstance(roles,dict) and set(roles)==INPUTS, 'Declare every canonical source input role')
    require(all(isinstance(roles[k],str) for k in REQUIRED_INPUTS), 'Missing required source input role')
    require(all(value is None or isinstance(value,str) for value in roles.values()), 'Invalid source input pointer')
    sources = {}
    source_receipts = []
    for item in source_records:
        require(item['case'] in cohort, 'Source row is outside original cohort')
        inputs = {}
        for role,path in roles.items():
            if path is None:
                continue
            receipt = pointer(item['row'],path)
            verifier.receipt(receipt)
            inputs[role] = receipt
            source_receipts.append(dict(case=item['case'],role=role,source_row_pointer=item['pointer'],receipt=receipt))
        old = sources.setdefault(item['case'],dict(inputs=inputs))
        require(set(old['inputs'])==set(inputs) and all(old['inputs'][k]['sha256']==v['sha256'] for k,v in inputs.items()), 'Repeated source rows have different bytes')
    require(set(sources)==set(cohort), 'Source inventory omits original trials')
    report = dict(prepared=spec['prepared'],summary=spec['summary'],commit=spec['commit'],
        original_trial_count=len(cohort),summary_row_count=len(projected),source_row_count=len(source_records),
        emitted_alert_count=len(alert_rows),source_receipts=source_receipts,
        provider_native_receipts_revalidated=False,algorithm_execution_closure_revalidated=False)
    return dict(cases=sorted(cohort),sources=sources,rows=projected,index=output,report=report)


def merge_sources(first, second):
    if first is None:
        return second
    require(set(first)==set(second),'Component source cohorts differ')
    merged = {}
    for case in first:
        left,right=first[case]['inputs'],second[case]['inputs']
        require(REQUIRED_INPUTS<=set(left)&set(right),'Common source roles are incomplete')
        require(all(left[k]['sha256']==right[k]['sha256'] for k in set(left)&set(right)), 'Component source bytes or overlapping metadata differ')
        merged[case]=dict(inputs={**right,**left})
    return merged


def load_components(specs, expected_trials):
    require(type(expected_trials) is int and expected_trials>0,'Expected trial count must be positive')
    require(isinstance(specs,list) and bool(specs),'Require a nonempty ordered component list')
    verifier=Verifier();loaded={};sources=None
    for spec in specs:
        result=component(spec,verifier)
        require(spec['name'] not in loaded,'Duplicate component name')
        require(len(result['cases'])==expected_trials,'Component differs from declared full denominator')
        sources=merge_sources(sources,result['sources'])
        loaded[spec['name']]=result
    return loaded,sources,dict(verified_data_files=len(verifier.checked),declared_commits=sorted(verifier.commits))


def compose(cases,loaded):
    decisions=[]
    for case in cases:
        decision=dict(case=case,component='abstain',alert=None)
        for name,item in loaded.items():
            row=item['index'][case]
            if row['alert'] is not None:
                decision=dict(case=case,component=name,alert=row['alert'],
                    source_summary=item['report']['summary'],source_alert_pointer=row['alert_pointer'],
                    canonical_complete_alert_sha256=canonical(row['alert']))
                break
        decisions.append(decision)
    return decisions


def write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)
        stream.write('\n')


def prepare(args):
    specs=read(args.components)
    loaded,sources,verification=load_components(specs,args.expected_trials)
    record=dict(version=VERSION,policy=POLICY,precedence=list(loaded),components=specs,
        component_spec=frozen(args.components),cases=sorted(sources),trial_denominator=args.expected_trials,
        source_inventory=sources,component_verification={n:r['report'] for n,r in loaded.items()},verification=verification,
        algorithm=frozen(__file__),retrospective=True,provider_native_receipts_revalidated=False,
        fresh_provider_calls=0,fresh_native_executions=0,evaluation_labels_used=False,
        created_utc=datetime.now(timezone.utc).isoformat())
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    write(output/'prepared.json',record);write(output/'seal.json',frozen(output/'prepared.json'))
    return dict(trials=len(sources),precedence=list(loaded),prepared=frozen(output/'prepared.json'))


def run(args):
    root=Path(args.input);protocol=read(root/'prepared.json');verifier=Verifier()
    verifier.seal(dict(receipt=frozen(root/'seal.json'),pointer=''),frozen(root/'prepared.json'))
    require(protocol.get('version')==VERSION and protocol.get('policy')==POLICY,'Unexpected sealed summary protocol')
    require(protocol['algorithm']==frozen(__file__),'Composition implementation changed')
    require(read(verifier.receipt(protocol['component_spec']))==protocol['components'],'Component specification changed')
    loaded,sources,verification=load_components(protocol['components'],protocol['trial_denominator'])
    require(protocol['precedence']==list(loaded),'Frozen precedence differs')
    require(protocol['cases']==sorted(sources) and protocol['source_inventory']==sources,'Frozen source inventory differs')
    require(protocol['component_verification']=={n:r['report'] for n,r in loaded.items()} and protocol['verification']==verification,'Frozen component verification differs')
    decisions=compose(protocol['cases'],loaded)
    value=dict(version=VERSION,stage='complete',prepared=frozen(root/'prepared.json'),
        trial_denominator=len(decisions),decisions=decisions,alerts=[r for r in decisions if r['alert'] is not None],
        detector_alerts=sum(r['alert'] is not None for r in decisions),
        component_outputs={name:rows['rows'] for name,rows in loaded.items()},
        component_summaries={name:rows['report']['summary'] for name,rows in loaded.items()},
        provider_native_receipts_revalidated=False,algorithm_execution_closures_revalidated=False,
        retrospective=True,evaluation_labels_used=False,fresh_provider_calls=0,fresh_native_executions=0,
        independent_audit_complete=False)
    if (root/'summary.json').exists():
        existing=read(root/'summary.json')
        verifier.seal(dict(receipt=frozen(root/'summary_seal.json'),pointer=''),frozen(root/'summary.json'))
        require({k:v for k,v in existing.items() if k!='completed_utc'}==value,'Completed composition differs')
        return existing
    value['completed_utc']=datetime.now(timezone.utc).isoformat()
    write(root/'summary.json',value);write(root/'summary_seal.json',frozen(root/'summary.json'))
    return dict(trials=len(decisions),alerts=value['detector_alerts'],fresh_provider_calls=0,fresh_native_executions=0,
                provider_native_receipts_revalidated=False)


if __name__=='__main__':
    parser=argparse.ArgumentParser(__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('stage',choices=['prepare','run'])
    parser.add_argument('--components',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--expected-trials',type=int)
    parser.add_argument('--input',type=Path)
    args=parser.parse_args()
    if args.stage=='prepare' and any(getattr(args,k) is None for k in ('components','output','expected_trials')):
        parser.error('prepare requires --components, --output and --expected-trials')
    if args.stage=='run' and args.input is None:
        parser.error('run requires --input')
    print(json.dumps(prepare(args) if args.stage=='prepare' else run(args)))
