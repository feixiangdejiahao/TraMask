"""Syntax-grounded test inventory and conservative test-to-test relations."""
import ast, hashlib, itertools, json, re
from pathlib import Path
from tree_sitter import Language, Parser
import tree_sitter_go, tree_sitter_typescript
ROOT=Path(__file__).resolve().parents[1]
SKIP={'.git','.venv','node_modules','dist','vendor','__pycache__'}
def walk(node):
    yield node
    for child in node.children: yield from walk(child)
def extract(path, source, origin='repository'):
    rows=[]; suffix=Path(path).suffix
    def add(name,start,end,calls,assertions,literals,params,code):
        rows.append(dict(id=f'{path}:{start}:{name}',path=path,name=name,start_line=start,end_line=end,origin=origin,
                         calls=sorted(set(calls)),assertions=assertions,literals=literals[:100],parameters=params,source=code,
                         sha256=hashlib.sha256(code.encode()).hexdigest()))
    if suffix=='.py':
        try: tree=ast.parse(source)
        except SyntaxError: return []
        lines=source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) or not node.name.startswith('test'): continue
            nodes=list(ast.walk(node)); start=min([node.lineno]+[d.lineno for d in node.decorator_list])
            add(node.name,start,node.end_lineno,[ast.unparse(n.func) for n in nodes if isinstance(n,ast.Call)],
                [ast.unparse(n) for n in nodes if isinstance(n,ast.Assert) or isinstance(n,ast.Call) and ('assert' in ast.unparse(n.func).lower() or ast.unparse(n.func).endswith('raises'))],
                [repr(n.value) for n in nodes if isinstance(n,ast.Constant)],[a.arg for a in node.args.args], '\n'.join(lines[start-1:node.end_lineno]))
        # Trajectory reproduction scripts frequently have only top-level assertions.
        if not rows and origin=='trajectory' and any(isinstance(n,ast.Assert) for n in ast.walk(tree)):
            nodes=list(ast.walk(tree));add('<script>',1,len(lines),[ast.unparse(n.func) for n in nodes if isinstance(n,ast.Call)], [ast.unparse(n) for n in nodes if isinstance(n,ast.Assert)], [repr(n.value) for n in nodes if isinstance(n,ast.Constant)],[],source)
    elif suffix in {'.go','.ts','.tsx','.js'}:
        lang=Language(tree_sitter_go.language() if suffix=='.go' else tree_sitter_typescript.language_typescript()); tree=Parser(lang).parse(source.encode()); data=source.encode()
        txt=lambda n:data[n.start_byte:n.end_byte].decode(errors='replace')
        for node in walk(tree.root_node):
            if suffix=='.go':
                name=node.child_by_field_name('name')
                eligible=node.type=='function_declaration' and name is not None and txt(name).startswith('Test')
                label=txt(name) if eligible else ''
            else:
                func=node.child_by_field_name('function'); label=txt(func) if func else ''
                eligible=node.type=='call_expression' and bool(re.match(r'^(it|test)(\.|$)',label))
            if not eligible: continue
            nodes=list(walk(node)); calls=[txt(n.child_by_field_name('function')) for n in nodes if n.type=='call_expression' and n.child_by_field_name('function')]
            assertions=[txt(n) for n in nodes if n.type in {'call_expression','expression_statement'} and re.search(r'\b(expect|assert|require|Fatalf?|Errorf?)\b',txt(n)) and len(txt(n))<2000]
            literals=[txt(n) for n in nodes if n.type in {'string','interpreted_string_literal','raw_string_literal','int_literal','number','true','false'}]
            add(label,node.start_point.row+1,node.end_point.row+1,calls,assertions,literals,[],txt(node))
    return rows

def is_test(path): return bool(re.search(r'(^|/)(tests?|__tests__)/|(^|/)test_|_test\.go$|\.(test|spec)(-d)?\.',str(path)))
def main():
    for case in json.loads((ROOT/'data/cases.json').read_text()):
        base=ROOT/'data/cases'/case['id']; repo=base/'repository'; rows=[]
        for p in sorted(repo.rglob('*')):
            if p.is_file() and not set(p.relative_to(repo).parts)&SKIP and is_test(p.relative_to(repo)) and p.suffix in {'.py','.go','.ts','.tsx','.js'}:
                rows+=extract(str(p.relative_to(repo)),p.read_text(errors='replace'))
        commands=[]; snippets=[]
        trajectory=json.loads((base/'trajectory.json').read_text())
        for step in trajectory['steps']:
            for idx,call in enumerate(step.get('tool_calls',[])):
                args=call.get('arguments',{});args=json.loads(args) if isinstance(args,str) else args
                command=args.get('command',''); sid=step['step_id']
                if re.search(r'pytest|go test|vitest|pnpm.*test|python\S*\s|assert',command):
                    commands.append({'step':sid,'call_index':idx,'command':command,'observation':step.get('observation',{})})
                # This is extraction only, never host-side execution of historical shell text.
                for n,m in enumerate(re.finditer(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n(.*?)\n\1(?:\n|$)",command,re.S)):
                    header=command[:m.start()].splitlines()[-1] if command[:m.start()].splitlines() else ''
                    ext='.go' if '.go' in header else '.ts' if '.ts' in header else '.py' if 'python' in header or '.py' in header else '.txt'
                    code=m.group(2); label=f'trajectory/step-{sid}-{idx}-{n}{ext}'
                    if re.search(r'assert|expect\(|testing\.T|pytest|\.Call\(',code):
                        snippets.append({'path':label,'source':code,'step':sid,'extraction':'literal heredoc, historical version'})
                        rows+=extract(label,code,'trajectory')
        patch=(base/'model.patch').read_text(); changed=re.findall(r'^\+\+\+ b/(.+)$',patch,re.M)
        additions={}; current=None; line=0
        for patch_line in patch.splitlines():
            if patch_line.startswith('+++ b/'): current=patch_line[6:]; additions.setdefault(current,set())
            elif patch_line.startswith('@@'):
                match=re.search(r'\+(\d+)',patch_line)
                if match: line=int(match.group(1))
            elif current and patch_line.startswith('+'):
                additions[current].add(line); line+=1
            elif patch_line.startswith(' '):line+=1
        identifiers=set(re.findall(r'\b[A-Za-z_]\w{3,}\b','\n'.join(l[1:] for l in patch.splitlines() if l.startswith('+') and not l.startswith('+++'))))
        for row in rows:
            row['relevance_score']=sum(bool(set(re.findall(r'\w+',c))&identifiers) for c in row['calls'])+ (100 if row['path'] in changed else 0)+(15 if row['origin']=='trajectory' else 0)
            row['changed_test_lines']=sorted(additions.get(row['path'],set()) & set(range(row['start_line'],row['end_line']+1)))
            row['relevance_score']+=200 if row['changed_test_lines'] else 0
            row['oracle_kind']='assertion' if row['assertions'] else 'execution_only_or_helper_oracle'
        ranked=sorted(rows,key=lambda x:-x['relevance_score']); selected=ranked[:100]
        edges=[]
        ignored={'len','str','int','print','range','list','dict','enumerate','isinstance','expect','t.Fatal','t.Fatalf','t.Error','t.Errorf'}
        for a,b in itertools.combinations(selected,2):
            common=set(a['calls'])&set(b['calls'])-ignored
            if common: edges.append({'source':a['id'],'target':b['id'],'relation':'shared_call_syntax','evidence':sorted(common),'semantic_identity_proven':False})
            fixtures=set(a['parameters'])&set(b['parameters'])-{'self','cls'}
            if fixtures: edges.append({'source':a['id'],'target':b['id'],'relation':'shared_parameter_or_fixture_name','evidence':sorted(fixtures)})
        out=ROOT/'results'/case['id'];out.mkdir(exist_ok=True)
        for name,value in [('tests',rows),('relations',edges),('commands',commands),('snippets',snippets)]: (out/f'{name}.json').write_text(json.dumps(value,indent=2,ensure_ascii=False))
        # Bounded evidence payload; model must cite test ids rather than invent provenance.
        budget=105000; chosen=[]
        for row in ranked:
            size=len(json.dumps(row))
            if size<=budget: chosen.append(row); budget-=size
            if len(chosen)>=65:break
        prod=[]
        for p in changed:
            file=repo/p
            if file.is_file() and not is_test(p) and len(file.read_bytes())<100000:
                prod.append({'path':p,'source':file.read_text(errors='replace')})
        payload={'case':case['id'],'issue':(base/'issue.md').read_text(),'tests':chosen,'relations':[e for e in edges if e['source'] in {r['id'] for r in chosen} and e['target'] in {r['id'] for r in chosen}][:100], 'candidate_patch':patch,'candidate_source':[],'scope':{'inventory_count':len(rows),'selected_count':len(chosen),'selection':'patch identifiers + changed tests + trajectory scripts; bounded static slice; no execution coverage claim'}}
        (out/'worker_input.json').write_text(json.dumps(payload,ensure_ascii=False))
        print(case['id'],len(rows),'tests;',len(chosen),'selected;',len(edges),'edges',flush=True)
if __name__=='__main__':main()
