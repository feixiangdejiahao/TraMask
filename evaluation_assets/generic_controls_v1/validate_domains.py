from pathlib import Path
import importlib.util,json,subprocess,tempfile,shutil,os
base=Path('/home/jhx/combination_coverage/data/generic_controls_v1')
private=Path('/tmp/cc-generic-evaluator-v1')
gold=json.loads((private/'oracle_table.json').read_text()); replacements=json.loads((private/'correct_replacements.json').read_text())
records=[]
for cid in ['C01','C02','C03']:
 path=base/cid/'repository/library.py'
 mod=importlib.util.module_from_spec(importlib.util.spec_from_file_location(cid,path));exec(path.read_text(),mod.__dict__)
 actual=[]
 for row in gold[cid]['rows']:
  if cid=='C01':
   vals=list(row['args'][0]);out=mod.canonical(vals);assert vals==row['unchanged_input']
  elif cid=='C02':out=mod.area(*row['args'])
  else:
   left=[row['left']];right=left if row['same_object'] else [row['right']]
   out=mod.bump_and_read(left,right,row['amount'])
  actual.append(out)
 errors=[i for i,(out,row) in enumerate(zip(actual,gold[cid]['rows'])) if out!=row['expected']]
 records.append({'id':cid,'rows':len(actual),'candidate_mismatch_indices':errors})
 if cid in replacements:
  scope={};exec(replacements[cid]['library.py'],scope)
  assert all(scope['area'](*r['args'])==r['expected'] for r in gold[cid]['rows'])
 else:assert not errors
for cid in ['C04','C05','C06']:
 with tempfile.TemporaryDirectory(prefix=cid+'_domain_') as tmp:
  dest=Path(tmp);shutil.copytree(base/cid/'repository',dest,dirs_exist_ok=True)
  table=json.dumps(gold[cid]['rows'])
  common='package controls\nimport("encoding/json";"testing";"reflect")\nvar _ = reflect.DeepEqual\nfunc TestIndependentDomain(t *testing.T) {\n var rows []map[string]interface{}\n if err:=json.Unmarshal([]byte(`'+table+'`), &rows);err!=nil {t.Fatal(err)}\n for i,row:=range rows {\n'
  if cid=='C04':body='r:=&Recorder{};want:=[]string{};for _,v:=range row["submissions"].([]interface{}) {r.Submit(v.(string));want=append(want,v.(string))};if r.Count()!=int(row["count"].(float64)) || !reflect.DeepEqual(r.Items(),want) {t.Fatalf("row %d",i)}'
  elif cid=='C05':body='r:=&Counter{Value:int(row["initial"].(float64))};for _,v:=range row["operations"].([]interface{}) {if v.(string)=="double" {r.Double()} else {r.Add(1)}};if r.Value!=int(row["expected"].(float64)) {t.Fatalf("row %d",i)}'
  else:body='a:=row["args"].([]interface{});out,err:=Quotient(int(a[0].(float64)),int(a[1].(float64)));if row["error"].(bool) {if err==nil {t.Fatalf("row %d",i)}} else if err!=nil || out!=int(row["expected"].(float64)) {t.Fatalf("row %d",i)}'
  (dest/'domain_test.go').write_text(common+body+'\n}\n}\n')
  r=subprocess.run(['go','test','./...'],cwd=dest,capture_output=True,text=True,timeout=30,env={**os.environ,'GOTOOLCHAIN':'local'})
  assert r.returncode==0,r.stdout+r.stderr
  records.append({'id':cid,'rows':len(gold[cid]['rows']),'candidate_mismatch_indices':[]})
for cid in ['C07','C08']:
 for variant in ['candidate','correct'] if cid in replacements else ['candidate']:
  with tempfile.TemporaryDirectory(prefix=cid+'_domain_') as tmp:
   dest=Path(tmp);shutil.copytree(base/cid/'repository',dest,dirs_exist_ok=True)
   if variant=='correct':
    for name,content in replacements[cid].items():(dest/name).write_text(content)
   body='const q=new Queue(row.values); return {taken:q.take(row.n),remaining:q.remaining()};' if cid=='C07' else 'return summarize(row.values);'
   symbol='Queue' if cid=='C07' else 'summarize'
   code='import { '+symbol+' } from "./library.ts";\nconst rows='+json.dumps(gold[cid]['rows'])+';\nconsole.log(JSON.stringify(rows.map((row) => {'+body+'})));\n'
   (dest/'domain.ts').write_text(code)
   r=subprocess.run(['node','domain.ts'],cwd=dest,capture_output=True,text=True,timeout=30);assert r.returncode==0,r.stderr
   actual=json.loads(r.stdout)
   expected=[{'taken':x['taken'],'remaining':x['remaining']} if cid=='C07' else x['expected'] for x in gold[cid]['rows']]
   errors=[i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b]
   if variant=='correct' or cid not in replacements:assert not errors
   records.append({'id':cid,'variant':variant,'rows':len(actual),'candidate_mismatch_indices':errors})
(private/'validation.json').write_text(json.dumps(records,indent=2)+'\n')
print('validated_cases',len(gold),'bounded_rows',sum(len(x['rows']) for x in gold.values()),'correct_controls_and_corrected_versions_match_table',True)
