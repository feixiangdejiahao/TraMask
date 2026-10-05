"""Read-only, non-LLM trajectory gap hypotheses. Never executes repository code.

This recall-oriented pilot keeps source/command association distinct from
runtime proof and normative oracle support. It does not consume evaluator data.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, CALLS, child, call_parts, is_test_path, units, walk
from relational_gap.history import recover_history

VERSION = 'trajectory-gap-source-pilot.v2'
RULES = ['validation_before_later_related_edit', 'returned_value_without_assertion_link',
         'type_only_nonidentity_behavior', 'object_presence_controls_field_behavior',
         'predicate_write_insensitivity', 'planned_call_not_visible_in_execution']
POLICY = dict(version=VERSION, selection='All seventeen frozen source trials; no case/API whitelist, model, target execution, labels or prior candidate outcomes.',
    ranking='Rule order, association strength, source path/start, trajectory ordinal, stable ID. No result-based reordering.',
    history='Recover literal writes/appends and bounded pure edits with existing history reader. Associate commands by literal path/test name or inline snippet. Unknown edits and execution contexts stay explicit.',
    observations='Historical shell success is a command receipt, never a valid oracle or final-version pass. Missing literal command evidence does not prove absence of execution.',
    domain='Python/Go/TypeScript syntax. SQL read/write rule handles literal COUNT/update or disjoint literal column mentions only. Presence guards and member-condition whole-field returns are syntactic hypotheses, not partial-update/defaults bugs.',
    evidence='Full original source tests and referenced complete trajectory steps stored separately and hash-linked. All hypotheses retained; no top-k truncation.',
    forbidden='No hidden/reference/evaluator inputs; no task identity in rule matching; no network or repository execution.')
RUN = re.compile(r'\b(?:pytest|unittest|go\s+(?:test|run)|(?:npx\s+)?(?:tsx|ts-node)|node|vitest|jest|npm\s+(?:run\s+)?test|pnpm\s+(?:run\s+)?test|python[0-9.]*)\b')
EDIT = re.compile(r'write_(?:text|bytes)\s*\(|\.write\s*\(|\b(?:apply_patch|sed\s+-i|perl\s+-[a-z]*i)\b|\bcat\b[^\n]*>{1,2}|\*\*\*\s+(?:Update|Add|Delete) File:')
PATH = re.compile(r"[A-Za-z0-9_./-]+\.(?:py|go|tsx?)(?![\w.])")
IDENT = re.compile(r'[A-Za-z_$][\w$]*')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def receipt(path):
    path=Path(path).resolve();return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())

def read_receipt(value):
    if receipt(value['path']) != value: raise ValueError('Source receipt changed: '+value['path'])
    return json.loads(Path(value['path']).read_text())

def text_at(corpus, span):
    return corpus['sources'][span['path']]['code'].encode()[span['start_byte']:span['end_byte']].decode()

def span(source,node):
    return dict(path=source.path,start_byte=node.start_byte,end_byte=node.end_byte,line=node.start_point.row+1,end_line=node.end_point.row+1,text=source.text(node),source_sha256=hashlib.sha256(source.data).hexdigest())

def leaf(text):
    names=IDENT.findall(text);return names[-1] if names else ''

def call_names(source,node):
    return {leaf(source.text(call_parts(n)[0])) for n in walk(node) if n.type in CALLS}

def events(trajectory):
    out=[]
    for ordinal,step in enumerate(trajectory.get('steps',[])):
        for ci,call in enumerate(step.get('tool_calls',[])):
            args=call.get('arguments',{})
            if isinstance(args,str):
                try:args=json.loads(args)
                except ValueError:continue
            if not isinstance(args,dict):continue
            command=args.get('command',args.get('cmd',''))
            if not isinstance(command,str):continue
            out.append(dict(ordinal=ordinal,step_id=step.get('step_id'),call_index=ci,command=command,
                function_name=call.get('function_name'),sequence=len(out),is_run=bool(RUN.search(command)),is_edit=bool(EDIT.search(command)),
                mentioned_paths=sorted(set(PATH.findall(command))),step_sha256=digest(step)))
    return out

def path_match(spelling,path):
    spelling=spelling.removeprefix('./');path=path.removeprefix('./')
    return spelling==path or spelling.endswith('/'+path)

def nonidentity_arrows(source,node):
    found=[]
    for n in walk(node):
        if n.type not in {'arrow_function','lambda','function_expression','func_literal'} or n==node:continue
        body=child(n,'body')
        if body is None:continue
        params=child(n,'parameters','parameter');names=IDENT.findall(source.text(params)) if params is not None else []
        code=source.text(body).strip()
        # Registration callbacks contain assertions/setup; they are not value transformations.
        if body.type in {'statement_block','block'} and any(x.type in CALLS and re.search(r'\b(?:assert|expect|require)\b',source.text(call_parts(x)[0])) for x in walk(body)):continue
        identity=bool(names) and (code in names or bool(re.fullmatch(r'\{?\s*return\s+'+re.escape(names[0])+r'\s*;?\s*\}?',code)))
        kinds=sorted({x.type for x in walk(body) if x.type in CALLS|{'binary_expression','binary_operator','member_expression','attribute','subscript_expression','subscript','object','object_creation_expression'}})
        if not identity and kinds:found.append(dict(span=span(source,n),shape=kinds))
    return found


def extract(corpus,frontend,trajectory,issue=''):
    ev=events(trajectory);steps={str(s.get('step_id')):s for s in trajectory.get('steps',[])}
    ordinal={str(s.get('step_id')):i for i,s in enumerate(trajectory.get('steps',[]))}
    sources={p:r for p,r in corpus['sources'].items() if r.get('origin')=='repository'}
    parsed={p:Source(p,r['code'],r.get('language',corpus['language']),'repository') for p,r in sources.items()}
    tests={};test_calls={};test_by_name=defaultdict(list);source_units={};functions={}
    for p,s in parsed.items():
        us,_=units(s);source_units[p]=us
        for u in us:
            if not u.test and not is_test_path(p):functions[u.id]=dict(name=u.name,path=p,code=s.text(u.node),span=span(s,u.node),calls=call_names(s,u.node))
    # The existing frontend also inventories assigned arrow functions.
    for f in frontend.get('functions',[]):
        if f.get('production') and f['span']['path'] in parsed and f['id'] not in functions:
            sp=f['span'];s=parsed[sp['path']];node=s.root.named_descendant_for_byte_range(sp['start_byte'],sp['end_byte']-1)
            functions[f['id']]=dict(name=f['name'],path=sp['path'],code=text_at(corpus,sp),span=span(s,node),calls=call_names(s,node))
    fn_by_name=defaultdict(set)
    for k,f in functions.items():fn_by_name[f['name']].add(k)
    for tid,t in corpus['tests'].items():
        if t['span']['path'] not in sources:continue
        code=text_at(corpus,t['span']);s=parsed[t['span']['path']]
        node=s.root.named_descendant_for_byte_range(t['span']['start_byte'],max(t['span']['start_byte'],t['span']['end_byte']-1))
        tests[tid]=dict(id=tid,origin='repository',path=t['span']['path'],span=t['span'],code=code,sha256=hashlib.sha256(code.encode()).hexdigest(),name=t['name'],retrieval_rank=t.get('retrieval_rank'),type_only=s.type_only,step_ids=[])
        test_calls[tid]=call_names(s,node);test_by_name[t['name']].append(tid)
    history,recovery=recover_history(trajectory,corpus['language'])
    for s in history:
        if s.root.has_error:continue
        us,_=units(s);validation=[u for u in us if u.test]
        if not validation and (is_test_path(s.written_path or '') or any(n.type in CALLS and leaf(s.text(call_parts(n)[0])) in {'print','log','Println','Printf'} for n in walk(s.root))):
            validation=[None]
        for u in validation:
            node=u.node if u else s.root;code=s.text(node);tid='history:'+digest([s.path,node.start_byte,node.end_byte])[:24]
            tests[tid]=dict(id=tid,origin='trajectory',path=s.path,original_path=s.written_path,span=span(s,node),code=code,sha256=hashlib.sha256(code.encode()).hexdigest(),name=u.name if u else '<script>',type_only=s.type_only,step_ids=[s.step],created_ordinal=ordinal.get(str(s.step),-1))
            test_calls[tid]=call_names(s,node)
    gaps=[];dedupe=set();referenced=set()
    def add(rule,test_ids,facts,step_ids=(),strength='source_hypothesis',where=None):
        tids=sorted(set(test_ids));all_steps=[*step_ids,*[x for tid in tids for x in tests[tid]['step_ids']]]
        ss=sorted({str(x) for x in all_steps if str(x) in steps},key=lambda x:ordinal[x])
        # Receipt hashes retain outcomes; structural ranking must not read them.
        def structure(value):
            if isinstance(value,dict):return {k:structure(v) for k,v in value.items() if k!='step_sha256'}
            if isinstance(value,list):return [structure(v) for v in value]
            return value
        key=digest([rule,tids,structure(facts),ss])
        if key in dedupe:return
        dedupe.add(key);referenced.update(ss)
        location=where or (tests[tids[0]]['span'] if tids else {})
        score={'resolved_source':0,'source_hypothesis':1,'lexical_weak':2}[strength]
        gaps.append(dict(id='gap_'+key[:24],rule=rule,strength=strength,test_ids=tids,step_ids=ss,evidence=facts,
            oracle_status='unconfirmed_requires_public_contract_and_complete_test_review',execution_status='no_new_execution',
            trajectory_link_status='exact_step_receipts_weak_semantic_association' if ss else 'source_only_no_specific_trajectory_association',candidate_test_status='source_tests_available' if tids else 'no_associated_test_found',
            order=[RULES.index(rule),score,location.get('path',''),location.get('start_byte',0),min((ordinal[x] for x in ss),default=-1),key],
            ranking_reason=dict(rule_priority=RULES.index(rule),association_strength=score,source_order=True,outcomes_used_for_ranking=False)))
    # Retain exact edit mentions. This does not recover arbitrary shell/Python edits.
    edits=[]
    for e in ev:
        if not e['is_edit']:continue
        paths=[p for p in parsed if not is_test_path(p) and any(path_match(x,p) for x in e['mentioned_paths'])]
        if paths:edits.append(dict(event=e,paths=paths))
    for tid,t in tests.items():
        if t['origin']!='trajectory':continue
        created=t['created_ordinal'];names=test_calls[tid]
        related={f['path'] for f in functions.values() if f['name'] in names}
        if not related:continue
        original=t.get('original_path')
        runs=[e for e in ev if e['is_run'] and e['ordinal']>=created and
            ((original and any(path_match(x,original) or path_match(original,x) for x in e['mentioned_paths'])) or
             (t['name']!='<script>' and t['name'] in e['command']) or
             (e['ordinal']==created and ('<<' in e['command'] or ' -c ' in e['command'])))]
        for change in edits:
            hit=sorted(related & set(change['paths']));ce=change['event']
            earlier=[r for r in runs if r['sequence']<ce['sequence']]
            later=[r for r in runs if r['sequence']>ce['sequence']]
            if hit and earlier and not later:
                last=earlier[-1]
                add(RULES[0],[tid],dict(related_production_paths=hit,association='callee_leaf_name_to_final_source_declaration',validation_command=last,subsequent_edit=ce,later_literal_matching_validation_found=False,limitation='Broad suite runs, helper dispatch and overwritten versions may defeat lexical command matching. No past pass or final-version coverage is inferred.'),[t['step_ids'][0],last['step_id'],ce['step_id']],strength='lexical_weak')
    # Resolved original calls with no linked assertion; returned values may be intentionally unused.
    ffront={f['id']:f for f in frontend.get('functions',[])}
    observed=defaultdict(set)
    for o in frontend.get('observations',[]):
        if o.get('kind')=='assertion':observed[o['test_id']].update(o.get('source_call_ids',[]))
    for c in frontend.get('calls',[]):
        tid=c['test_id']
        if tid not in tests or c['id'] in observed[tid] or c.get('role')=='oracle':continue
        targets=[ffront[x['function_id']] for x in c.get('targets',[]) if x.get('resolved') and x['function_id'] in ffront and ffront[x['function_id']].get('production')]
        targets=[f for f in targets if leaf(f['name']) not in {'__init__','constructor'} and re.search(r'\breturn\s+[^\n;}]+',text_at(corpus,f['span']))]
        if not targets:continue
        s=parsed[c['span']['path']];n=s.root.named_descendant_for_byte_range(c['span']['start_byte'],c['span']['end_byte']-1)
        ancestors=[];p=n.parent
        while p is not None and p.start_byte>=tests[tid]['span']['start_byte']:
            ancestors.append(p);p=p.parent
        discarded=bool(n.parent and n.parent.type in {'expression_statement','go_statement'})
        printed=any(p.type in CALLS and leaf(s.text(call_parts(p)[0])) in {'print','log','Println','Printf'} for p in ancestors)
        add(RULES[1],[tid],dict(call=c,production_targets=[dict(id=f['id'],span=f['span'],name=f['name']) for f in targets],direct_discard=discarded,printed=printed,reason='no_assertion_source_call_link_in_frozen_frontend',limitation='Void/effectful calls, indirect or unresolved assertions and intentionally ignored results can be benign.'),strength='resolved_source',where=c['span'])
    for tid,t in tests.items():
        if t['origin']!='trajectory':continue
        s=Source(t['path'],t['code'],corpus['language'],'trajectory');calls=test_calls[tid]
        printed=bool(calls & {'print','log','Println','Printf'});asserted=any(n.type=='assert_statement' or n.type in CALLS and re.search(r'(?i)(?:assert|expect|require|fatal|errorf|raises)',s.text(call_parts(n)[0])) for n in walk(s.root))
        actual=sorted(calls & set(fn_by_name))
        if printed and not asserted and actual:add(RULES[1],[tid],dict(reason='historical_print_only_validation',production_callee_name_matches=actual,limitation='Name association only; printed values can have been manually inspected.'),t['step_ids'],strength='lexical_weak')
    # Type files need not be in the bounded runtime test catalog; enumerate source units too.
    runtime_calls=defaultdict(list)
    for tid,t in tests.items():
        if not t['type_only']:
            for name in test_calls[tid]:runtime_calls[name].append(tid)
    for p,s in parsed.items():
        if not s.type_only:continue
        for u in source_units[p]:
            if not u.test:continue
            tid='type:'+digest([p,u.node.start_byte])[:24];cs=call_names(s,u.node);arrows=nonidentity_arrows(s,u.body)
            if not arrows:continue
            tests[tid]=dict(id=tid,origin='repository',path=p,span=span(s,u.node),code=s.text(u.node),sha256=hashlib.sha256(s.text(u.node).encode()).hexdigest(),name=u.name,type_only=True,step_ids=[])
            test_calls[tid]=cs
            related=sorted({x for c in cs & set(fn_by_name) for x in runtime_calls[c]})
            add(RULES[2],[tid,*related],dict(nonidentity_functions=arrows,shared_production_callee_names=sorted(cs & set(fn_by_name)),runtime_association='same_leaf_callee_name_only',runtime_nonidentity_coverage='not_established',limitation='Type-only behavior is source evidence; no assertion that compiler executed value behavior or runtime tests omit every equivalent operation.'),strength='source_hypothesis',where=span(s,u.node))
    # Source-only object-level null/existence branch controlling field access.
    for fid,f in functions.items():
        s=parsed[f['path']];n=s.root.named_descendant_for_byte_range(f['span']['start_byte'],f['span']['end_byte']-1)
        related=[tid for tid,cs in test_calls.items() if f['name'] in cs]
        if not related:continue
        for branch in walk(n):
            if branch.type not in {'if_statement','conditional_expression','ternary_expression'}:continue
            cond=child(branch,'condition');body=child(branch,'consequence','body')
            if cond is None or body is None:continue
            condition=s.text(cond);ids=IDENT.findall(condition)
            simple=cond.type in {'identifier','parenthesized_expression','unary_expression','not_operator'} or bool(re.search(r'\b(?:None|null|undefined|nil)\b',condition))
            condition_members=[x for x in walk(cond) if x.type in {'attribute','member_expression','selector_expression'}]
            branch_returns=[x for x in walk(body) if x.type=='return_statement']
            all_returns=[x for x in walk(n) if x.type=='return_statement']
            member_dispatch=bool(condition_members and branch_returns and len(all_returns)>len(branch_returns))
            if not simple and not member_dispatch:continue
            fields=defaultdict(set)
            for x in walk(body):
                if x.type in {'attribute','member_expression','selector_expression'}:
                    obj=child(x,'object','value','operand');name=child(x,'attribute','property','field')
                    if obj is not None and name is not None:fields[s.text(obj)].add(s.text(name))
            touched={obj:sorted(vals) for obj,vals in fields.items() if len(vals)>=2 and (obj in ids or any(i in IDENT.findall(obj) for i in ids))}
            if touched:add(RULES[3],related,dict(shape='presence_guard_multiple_fields',function=f['span'],guard=span(s,cond),controlled_fields=touched,branch=span(s,branch),limitation='A whole-object guard may be correct. Field defaults, omitted-field legality and partial update obligations require public contracts.'),strength='source_hypothesis',where=span(s,branch))
            if member_dispatch:
                returned_members=[x for r in branch_returns for x in walk(r) if x.type in {'attribute','member_expression','selector_expression'}]
                if returned_members:
                    add(RULES[3],related,dict(shape='member_condition_whole_field_return',function=f['span'],guard=span(s,cond),returned_fields=[span(s,x) for x in returned_members],other_return_sites=[span(s,x) for x in all_returns if x not in branch_returns],branch=span(s,branch),limitation='Member truthiness can correctly select a complete object/value. Boolean type, defaults meaning, field completeness, execution reachability and partial-field obligations are not established.'),strength='source_hypothesis',where=span(s,branch))
    # Literal SQL evidence only. Count predicates are insensitive to field-only UPDATE absent triggers/etc.
    for tid,t in tests.items():
        code=t['code'];predicates=list(re.finditer(r'(?i)(?:count\s*\(\s*\*\s*\)|\b[A-Za-z_]\w*)\s*(?:<=|>=|<|>|=)\s*\d+',code));writes=list(re.finditer(r'(?i)\bUPDATE\s+([A-Za-z_]\w*)\s+SET\s+([^\n;\"\']+)',code))
        for pred in predicates:
            columns=set(IDENT.findall(pred.group()));count=bool(re.match(r'(?i)count\s*\(',pred.group()))
            for wr in writes:
                written=set(re.findall(r'\b([A-Za-z_]\w*)\s*=',wr[2]))
                if written and (count or not columns & written):add(RULES[4],[tid],dict(predicate=pred.group(),predicate_char_span=[pred.start(),pred.end()],update=wr.group(),update_char_span=[wr.start(),wr.end()],read_columns=[] if count else sorted(columns),writes=sorted(written),count_preserving_update_hypothesis=count,limitation='Textual SQL association only. Table binding, actual execution, triggers, generated columns, row selection and related invariants remain unproved.'),t['step_ids'],strength='lexical_weak')
    # A literal planned call absent from later run commands/snippets is only a recall signal.
    for i,step in enumerate(trajectory.get('steps',[])):
        prose='\n'.join(str(step.get(k,'')) for k in ['message','reasoning_content'])
        if step.get('source') not in {'agent','assistant'}:continue
        calls=list(re.finditer(r'([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\([^()\n]{0,160}\)',prose))
        later='\n'.join(e['command'] for e in ev if e['ordinal']>=i and e['is_run'])
        normalized=re.sub(r'\s+','',later)
        for match in calls:
            name=leaf(match[1])
            if name not in fn_by_name:continue
            spelling=match.group()
            if re.sub(r'\s+','',spelling) in normalized:continue
            related=[tid for tid,cs in test_calls.items() if name in cs]
            add(RULES[5],related,dict(mentioned_call=spelling,prose_field_scope='message plus reasoning_content',prose_char_span=[match.start(),match.end()],same_name_production_functions=sorted(fn_by_name[name]),literal_occurrence_in_later_run_commands=False,limitation='Not a plan-intent proof or absence-of-execution proof. Dynamic construction, file-based tests, paraphrases and different formatting can explain the mismatch.'),[step.get('step_id')],strength='lexical_weak')
    gaps.sort(key=lambda g:g['order'])
    for rank,g in enumerate(gaps,1):g['rank']=rank
    return dict(version=VERSION,policy=POLICY,gaps=gaps,tests=tests,steps={k:steps[k] for k in sorted(referenced,key=lambda x:ordinal[x])},
        counts=dict(tests=len(tests),history_tests=sum(t['origin']=='trajectory' for t in tests.values()),gaps=len(gaps),by_rule=dict(Counter(g['rule'] for g in gaps)),trajectory_steps=len(trajectory.get('steps',[])),tool_events=len(ev),edit_events_with_repository_path=len(edits)),
        history_recovery=recovery,limitations=['All records are hypotheses, not bug verdicts.','Command outcomes are retained as original evidence only.','No negative result proves coverage; extraction is finite and syntax-dependent.','Full source code and step receipts may include benign or redundant contexts.'])


def main():
    parser=argparse.ArgumentParser(__doc__);parser.add_argument('--source-cohort',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    protocol=json.loads((args.source_cohort/'prepared.json').read_text());read_receipt(json.loads((args.source_cohort/'seal.json').read_text()))
    assert len(protocol['cases'])==17 and len({c['case'] for c in protocol['cases']})==17
    args.output.mkdir(parents=True,exist_ok=False);rows=[]
    frozen_algorithm=args.output/'algorithm_snapshot.py';frozen_algorithm.write_bytes(Path(__file__).read_bytes())
    for c in protocol['cases']:
        metadata=read_receipt(c['inputs']['case.json']);projection=read_receipt(c['review_projection']);corpus=read_receipt(projection['corpus']);frontend=read_receipt(projection['frontend'])
        tp=Path(metadata['trajectory']);trajectory=json.loads(tp.read_text());issue=Path(metadata['issue']).read_text()
        result=extract(corpus,frontend,trajectory,issue);directory=args.output/c['case'];directory.mkdir()
        evidence={}
        for field in ['tests','steps']:
            p=directory/(field+'.json');p.write_text(json.dumps(result.pop(field),ensure_ascii=False,indent=2)+'\n');evidence[field]=receipt(p)
        result.update(evidence_files=evidence,inputs=dict(corpus=projection['corpus'],frontend=projection['frontend'],trajectory=receipt(tp),issue=receipt(metadata['issue'])),trial=c['case'])
        p=directory/'gaps.json';p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');rows.append(dict(trial=c['case'],counts=result['counts'],result=receipt(p),evidence=evidence))
        print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    summary=dict(version=VERSION,policy=POLICY,source_cohort=receipt(args.source_cohort/'prepared.json'),algorithm=receipt(frozen_algorithm),original_algorithm_path=str(Path(__file__).resolve()),dependencies={str(p):receipt(p) for p in [ROOT/'relational_gap/history.py',ROOT/'anchor_retrieval/syntax.py']},trials=17,rows=rows,total_gaps=sum(r['counts']['gaps'] for r in rows),provider_calls=0,native_executions=0,labels_used=False)
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(summary=receipt(args.output/'summary.json'),total_gaps=summary['total_gaps']),ensure_ascii=False))

if __name__=='__main__':main()
