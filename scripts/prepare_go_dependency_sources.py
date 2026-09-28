"""Read package declaration evidence from already installed, offline Go images."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anchor_retrieval.syntax import Source, child, walk

EXTRACT = r'''import subprocess,json,pathlib,hashlib,os
imports=json.load(open('/source-requests.json'))
env=dict(os.environ,GOPROXY='off',GOSUMDB='off',GOTOOLCHAIN='local')
p=subprocess.run(['go','list','-e','-find','-json',*imports],cwd='/app',env=env,capture_output=True,text=True)
decoder=json.JSONDecoder();text=p.stdout;docs=[]
while text.strip():
 obj,end=decoder.raw_decode(text.lstrip());docs.append(obj);text=text.lstrip()[end:]
result={'import_package_sources':{},'errors':[],'go_list_returncode':p.returncode,'go_list_stderr':p.stderr,'scope':'offline installed dependency source files only'}
for doc in docs:
 directory=doc.get('Dir');name=doc.get('ImportPath')
 if not directory:
  result['errors'].append({'import_path':name,'error':doc.get('Error')});continue
 paths=[pathlib.Path(directory)/f for f in doc.get('GoFiles',[]) if (pathlib.Path(directory)/f).is_file()]
 if not paths:
  result['errors'].append({'import_path':name,'error':'no_GoFiles'});continue
 chosen=min(paths,key=lambda p:(p.stat().st_size,str(p)));data=chosen.read_bytes()
 result['import_package_sources'][name]=[{'path':str(chosen),'code':data.decode(),'sha256':hashlib.sha256(data).hexdigest(),'go_list_name':doc.get('Name')}]
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    extractor = args.output / 'extractor.py'
    extractor.write_text(EXTRACT)
    for case_file in sorted(args.batch_root.glob('*/case.json')):
        case = json.loads(case_file.read_text())
        if case['language'] != 'go':
            continue
        case_id = case_file.parent.name
        target = args.output / (case_id + '.json')
        if target.exists():
            print(json.dumps({'case': case_id, 'status': 'existing_preserved'}), flush=True)
            continue
        corpus = json.loads((case_file.parent / 'corpus.json').read_text())
        selection = json.loads((case_file.parent / 'selection.json').read_text())
        modules = set()
        for path, meta in selection['files'].items():
            if not path.endswith('.go') or meta.get('kind') != 'historical_validation' or path not in corpus['sources']:
                continue
            source = Source(path, corpus['sources'][path]['code'], 'go')
            for node in walk(source.root):
                if node.type == 'import_spec':
                    value = child(node, 'path')
                    if value:
                        modules.add(json.loads(source.text(value)))
        request = args.output / (case_id + '_requests.json')
        request.write_text(json.dumps(sorted(modules), indent=2) + '\n')
        command = ['docker', 'run', '--rm', '--pull', 'never', '--network', 'none', '--cpus', '2', '--memory', '4g',
                   '--entrypoint', 'python3', '--mount', f'type=bind,source={extractor.resolve()},target=/extract.py,readonly',
                   '--mount', f'type=bind,source={request.resolve()},target=/source-requests.json,readonly',
                   case['image'], '/extract.py']
        process = subprocess.run(command, capture_output=True, text=True, timeout=120)
        if process.returncode:
            raise RuntimeError(f'{case_id}: dependency extraction failed: {process.stderr[-2000:]}')
        result = json.loads(process.stdout)
        result.update(image=case['image'], request_sha256=hashlib.sha256(request.read_bytes()).hexdigest(),
                      extractor_sha256=hashlib.sha256(extractor.read_bytes()).hexdigest())
        target.write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({'case': case_id, 'packages': len(result['import_package_sources']),
                          'errors': len(result['errors'])}), flush=True)


if __name__ == '__main__':
    main()
