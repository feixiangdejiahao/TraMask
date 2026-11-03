"""Read-only, case-independent qualification of unchanged initialized gitlinks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


COLLECT_GITLINKS = r'''
import hashlib,json,os,stat,subprocess,sys
request=json.load(sys.stdin);root=request.get('root','/app')
env={k:v for k,v in os.environ.items() if not k.startswith('GIT_CONFIG_') and k not in
     {'GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE','GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES'}}
env.update(GIT_OPTIONAL_LOCKS='0',GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_SYSTEM=os.devnull)
def git(where,*args,options=()):
    p=subprocess.run(['git','--no-optional-locks','-c','safe.directory=*','-c','core.fsmonitor=false',
                      '-c','core.untrackedCache=false',*options,'-C',where,*args],capture_output=True,env=env)
    if p.returncode:raise RuntimeError(json.dumps({'argv':list(args),'returncode':p.returncode,'stderr':p.stderr.decode(errors='replace')}))
    return p.stdout
def file_hash(path):
    try:
        with open(path,'rb') as stream:return hashlib.sha256(stream.read()).hexdigest()
    except FileNotFoundError:return None
def entries(raw,tree=False):
    result={}
    for row in raw.split(b'\0'):
        if not row:continue
        header,path=row.split(b'\t',1);parts=header.split()
        if tree:mode,kind,oid=parts;stage=0
        else:mode,oid,stage=parts;stage=int(stage)
        value={'mode':mode.decode(),'oid':oid.decode(),'stage':stage}
        name=os.fsdecode(path)
        if name in result:result[name].setdefault('other_stages',[]).append(value)
        else:result[name]=value
    return result
def walk_tree(where):
    rows=[];errors=[]
    for directory,dirs,files in os.walk(where,followlinks=False,onerror=lambda e:errors.append(str(e))):
        dirs[:]=sorted(n for n in dirs if n!='.git')
        for name in sorted(dirs+[n for n in files if n!='.git']):
            path=os.path.join(directory,name)
            try:
                before=os.lstat(path);item={'path':os.path.relpath(path,where),'permissions':stat.S_IMODE(before.st_mode)}
                if stat.S_ISLNK(before.st_mode):item.update(kind='symlink',target=os.readlink(path))
                elif stat.S_ISDIR(before.st_mode):item.update(kind='directory')
                elif stat.S_ISREG(before.st_mode):
                    with open(path,'rb') as stream:data=stream.read()
                    item.update(kind='file',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
                else:item.update(kind='special')
                after=os.lstat(path)
                if any(getattr(before,k)!=getattr(after,k) for k in ('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')):
                    errors.append('concurrently_changed: '+item['path'])
                rows.append(item)
            except OSError as error:errors.append(str(error))
    return sorted(rows,key=lambda r:r['path']),errors
parent_before=git(root,'rev-parse','HEAD').decode().strip();results={}
for path in request['paths']:
    value={'path':path};results[path]=value
    try:
        if path.startswith('/') or any(p in ('','.', '..') for p in path.split('/')) or '\0' in path:
            raise ValueError('invalid_gitlink_path')
        where=os.path.join(root,path)
        for offset in range(1,len(path.split('/'))):
            if not stat.S_ISDIR(os.lstat(os.path.join(root,*path.split('/')[:offset])).st_mode):
                raise ValueError('non_directory_gitlink_ancestor')
        parent_entries=entries(git(root,'ls-tree','-z','HEAD','--',path),tree=True)
        value['parent_gitlink']=parent_entries.get(path)
        try:info=os.lstat(where)
        except FileNotFoundError:
            value.update(kind='missing',initialized=False);continue
        value.update(kind='directory' if stat.S_ISDIR(info.st_mode) else 'other',root_permissions=stat.S_IMODE(info.st_mode))
        if value['kind']!='directory':value['initialized']=False;continue
        top=git(where,'rev-parse','--show-toplevel').decode().strip()
        value.update(initialized=top==where,git_root=top)
        if not value['initialized']:continue
        index=git(where,'rev-parse','--git-path','index').decode().strip()
        if not os.path.isabs(index):index=os.path.join(where,index)
        index_before=file_hash(index)
        value['head']=git(where,'rev-parse','HEAD').decode().strip()
        value['head_tree']=git(where,'rev-parse','HEAD^{tree}').decode().strip()
        value['head_entries']=entries(git(where,'ls-tree','-r','-z','HEAD'),tree=True)
        value['index_entries']=entries(git(where,'ls-files','--stage','-z'))
        # Status must not invoke repository-defined clean/smudge/process programs.
        config=subprocess.run(['git','-C',where,'config','--local','--name-only','--get-regexp',r'^filter\..*\.(clean|smudge|process|required)$'],capture_output=True,env=env)
        if config.returncode not in (0,1):raise RuntimeError('filter_configuration_unavailable')
        options=[]
        for key in config.stdout.decode().splitlines():options.extend(['-c',key+'='+('false' if key.endswith('.required') else '')])
        value['status']=git(where,'status','--porcelain=v1','--untracked-files=all','--ignore-submodules=none',options=options).decode(errors='replace')
        value['tree'],value['tree_errors']=walk_tree(where)
        value['nested_gitlinks']=[p for p,v in value['head_entries'].items() if v['mode']=='160000']
        value['index_unchanged']=index_before==file_hash(index)
        value['head_unchanged']=value['head']==git(where,'rev-parse','HEAD').decode().strip()
        value['index_sha256_before']=index_before;value['index_sha256_after']=file_hash(index)
        value['git_metadata_excluded_from_literal_tree']=True
    except Exception as error:value['error']=type(error).__name__+': '+str(error)
print(json.dumps({'parent_head':parent_before,'parent_head_unchanged':parent_before==git(root,'rev-parse','HEAD').decode().strip(),
                  'gitlinks':results},ensure_ascii=True))
'''


def collect_gitlink_state(runtime, paths, out):
    """Capture a fresh clone's gitlink evidence without changing its index/files."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    request = {"root": "/app", "paths": sorted(set(paths))}
    process = runtime._control(["python3", "-I", "-c", COLLECT_GITLINKS],
                               input_bytes=json.dumps(request).encode(), timeout=180, check=False)
    (out / "stdout.bin").write_bytes(process.stdout)
    (out / "stderr.bin").write_bytes(process.stderr)
    if process.returncode:
        raise RuntimeError("gitlink_collector_failed: " + str(out))
    result = json.loads(process.stdout)
    result.update(image_id=runtime.image_id, runtime_initial_head=runtime.base_commit,
                  collector_sha256=hashlib.sha256(COLLECT_GITLINKS.encode()).hexdigest())
    (out / "snapshot.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def compare_gitlink(expected, baseline, actual):
    """Qualify one initialized gitlink from raw, independently collected facts."""
    unavailable, differences = [], []
    if not isinstance(baseline, dict) or not isinstance(actual, dict):
        return {"status": "unverified", "matched": False, "reasons": ["gitlink_evidence_missing"]}
    for label, value in (("original", baseline), ("checkpoint", actual)):
        if value.get("error") or value.get("tree_errors"):
            unavailable.append(label + "_gitlink_evidence_unreadable_or_unstable")
        if value.get("kind") != "directory" or value.get("initialized") is not True:
            (unavailable if label == "original" else differences).append(label + "_gitlink_missing_or_not_initialized")
            continue
        parent = value.get("parent_gitlink", {})
        if parent.get("mode") != "160000" or parent.get("oid") != expected["oid"]:
            (unavailable if label == "original" else differences).append(label + "_parent_gitlink_oid_differs")
        if value.get("head") != expected["oid"]:
            (unavailable if label == "original" else differences).append(label + "_nested_head_differs_from_gitlink")
        if value.get("index_entries") != value.get("head_entries") or not isinstance(value.get("head_entries"), dict):
            differences.append(label + "_nested_index_differs_from_head")
        if value.get("status") != "":
            differences.append(label + "_nested_worktree_not_clean")
        if value.get("head_unchanged") is not True or value.get("index_unchanged") is not True:
            unavailable.append(label + "_git_state_changed_during_collection")
        if value.get("nested_gitlinks"):
            unavailable.append(label + "_recursive_gitlinks_require_separate_qualification")
        if not isinstance(value.get("tree"), list):
            unavailable.append(label + "_literal_tree_missing")
        elif any(row.get("kind") not in {"file", "directory", "symlink"} for row in value["tree"]):
            unavailable.append(label + "_literal_tree_has_special_entries")
    if isinstance(baseline.get("tree"), list) and isinstance(actual.get("tree"), list):
        if baseline["tree"] != actual["tree"]:
            differences.append("literal_submodule_tree_differs_from_original_image")
        if baseline.get("root_permissions") != actual.get("root_permissions"):
            differences.append("submodule_root_permissions_differ")
    status = "mismatch" if differences else "unverified" if unavailable else "matched"
    return {"status": status, "matched": status == "matched", "reasons": differences + unavailable,
            "expected_gitlink_oid": expected["oid"], "original_nested_head": baseline.get("head"),
            "checkpoint_nested_head": actual.get("head"),
            "literal_entries_compared": len(actual.get("tree", [])),
            "scope": "Initialized gitlink OID, nested HEAD/index/status, and complete literal working tree equal to the original image; Git metadata excluded from literal tree."}
