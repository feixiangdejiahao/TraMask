"""Offline structural features and conservative combination plans, without an LLM."""
import ast,itertools,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IGNORED={'expect','Equal','NoError','True','False','Error','Contains','len','isinstance','str','int','print','range','list','dict','enumerate','toBe','toEqual','toStrictEqual','raises'}
def interface(call):
    name=re.sub(r'\([^()]*\)','()',call).split('.')[-1]
    return name if name not in IGNORED and not name.startswith('assert') else None

def features(row):
    src=row['source'];calls=[interface(x) for x in row['calls']];calls=sorted({x for x in calls if x})
    result={'test_id':row['id'],'interfaces':calls,'oracle_kind':row['oracle_kind'],'oracle_expressions':row['assertions'],
            'input_literals':row['literals'],'fixture_or_parameter_names':row['parameters'],'parameterizations':[],
            'action_sequence':[],'assignments':[],'asserted_fields':sorted(set(re.findall(r'\b\w+\.(\w+)', '\n'.join(row['assertions'])))),
            'object_structure':{'closure_syntax_count':len(re.findall(r'\bfunc\s*\(|=>|\blambda\b',src)),
                                'container_syntax':sorted(set(re.findall(r'\b(?:array|map|set|record|object|Array|Map)\b',src))),
                                'captured_cell_identity':'unknown_without_embedded_language_scope_analysis'},
            'coverage_status':'static_presence_only'}
    if row['path'].endswith('.py'):
        try:
            tree=ast.parse(src)
            for n in ast.walk(tree):
                if isinstance(n,ast.Call) and ast.unparse(n.func).endswith('parametrize'):
                    result['parameterizations'].append({'names':ast.unparse(n.args[0]),'values':ast.unparse(n.args[1]) if len(n.args)>1 else 'unknown'})
                if isinstance(n,(ast.Assign,ast.AnnAssign)):
                    result['assignments'].append(ast.unparse(n))
            result['action_sequence']=[{'line':n.lineno+row['start_line']-1,'call':ast.unparse(n.func),'args':[ast.unparse(a) for a in n.args]} for n in sorted((n for n in ast.walk(tree) if isinstance(n,ast.Call)),key=lambda n:(n.lineno,n.col_offset))]
        except SyntaxError: pass
    else:
        result['action_sequence']=[{'offset':m.start(),'call':m.group(1)} for m in re.finditer(r'\b([\w.]+)\s*\(',src)]
        result['sequence_precision']='lexical; nested calls are not execution order'
    return result

def main():
 for c in json.loads((ROOT/'data/cases.json').read_text()):
    out=ROOT/'results'/c['id'];rows=json.loads((out/'tests.json').read_text());fs=[features(r) for r in rows]
    (out/'features.json').write_text(json.dumps(fs,indent=2,ensure_ascii=False))
    candidates=[(r,f) for r,f in zip(rows,fs) if r['origin']=='repository' and r.get('changed_test_lines')]
    plans=[]
    for (a,fa),(b,fb) in itertools.combinations(candidates,2):
        shared=set(fa['interfaces'])&set(fb['interfaces']); onlya=set(fa['interfaces'])-set(fb['interfaces']);onlyb=set(fb['interfaces'])-set(fa['interfaces'])
        if not shared or not (onlya or onlyb):continue
        plans.append({'source_test_ids':[a['id'],b['id']],'common_interfaces':sorted(shared),
                      'context_A':sorted(onlya),'context_B':sorted(onlyb),
                      'action':'compose setup/input representation from one test with entry/context from the other; retain only contract-preserving assertions',
                      'oracle_candidates':a['assertions'][:4]+b['assertions'][:4],
                      'oracle_validity':'requires invariance check; not automatically transferable',
                      'missing_interaction_status':'unknown: syntactic candidate, not proof of absence',
                      'score':len(shared)+min(len(onlya),4)+min(len(onlyb),4)})
    plans=sorted(plans,key=lambda x:-x['score'])[:100]
    (out/'combination_plans.json').write_text(json.dumps(plans,indent=2,ensure_ascii=False))
    print(c['id'],len(fs),'feature records',len(plans),'structural plans')
if __name__=='__main__':main()
