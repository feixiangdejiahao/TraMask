"""Independent comparison with the tracked tree encoded by a submitted patch.

The expected tree is built in a temporary Git repository, index, and object
directory. Its checkout uses its own .gitattributes, including explicit EOL
rules; external content filters are refused. No patch is applied to replay
files or the real index. Comparison reads literal actual bytes, including
unchanged tracked files; actual clean filters, stat caches, and index flags
cannot erase differences.

The task's collection hook exports ``git diff --binary BASE HEAD``. Its oracle
therefore describes the committed HEAD tree, not necessarily the working tree.
The report checks replay HEAD and literal working-tree contents separately
against that independently constructed submitted tree. Untracked files,
ignored dependencies, /tmp, and live processes require separate evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from .runtime import Container


def compare_tracked_tree(observation: dict) -> dict:
    """Compare an independent expected index with literal working-tree records."""
    if observation.get("construction_error"):
        return {"status": "expected_tree_unavailable", "tracked_tree_matches": False,
                "submission_state_status": "unverified",
                "submitted_commit_tree_matches": None,
                "working_tree_matches_submitted_commit": False,
                "index_tree_matches_submitted_commit": None,
                "mismatches": [], "unverified": [observation["construction_error"]]}
    expected = observation["expected"]
    actual = observation["actual"]
    names = set(expected) | set(observation["base"]) | set(observation["current_index"])
    mismatches, unverified = [], []
    matched, absent = 0, 0
    for path in sorted(names):
        want_index, have = expected.get(path), actual[path]
        want = observation.get("expected_checkout", expected).get(path)
        reasons = []
        if have.get("error") or have.get("unstable_during_read"):
            unverified.append({"path": path, "reason": "unreadable_or_concurrently_changed",
                               "actual": have})
            continue
        if want_index is None:
            # Git trees contain files, links, and gitlinks, but do not track
            # directories. A deleted file can become an implicit directory;
            # a deleted descendant can be replaced by an ancestor symlink.
            if have["kind"] in {"missing", "directory", "blocked_ancestor"}:
                absent += 1
            else:
                reasons.append("present_but_absent_from_submitted_tree")
        elif want_index["mode"] == "160000":
            unverified.append({"path": path, "reason": "submodule_worktree_not_validated",
                               "expected": want_index, "actual": have})
            continue
        elif (path in observation.get("expected_checkout_unverified", {})
              or want is None or want.get("error") or want.get("unstable_during_read")
              or ("kind" in want and want["kind"] not in {"file", "symlink"})):
            unverified.append({"path": path, "reason": "expected_checkout_not_verified",
                               "details": observation.get("expected_checkout_unverified", {}).get(path),
                               "expected_index": want_index, "expected_checkout": want})
            continue
        else:
            expected_kind = "symlink" if want["mode"] == "120000" else "file"
            if have["kind"] != expected_kind:
                reasons.append("file_kind_or_presence_differs")
            else:
                if have["mode"] != want["mode"]:
                    reasons.append("git_mode_differs")
                if have["oid"] != want["oid"]:
                    reasons.append("literal_bytes_differ")
        if reasons:
            mismatches.append({"path": path, "reasons": reasons,
                               "expected": want, "actual": have})
        else:
            matched += want is not None
    if not observation.get("real_index_unchanged", False):
        unverified.append({"reason": "real_index_changed_during_validation"})
    if not observation.get("head_unchanged", False):
        unverified.append({"reason": "head_changed_during_validation"})
    working_matches = not mismatches and not unverified
    working_status = "mismatch" if mismatches else "unverified" if unverified else "matched"
    expected_tree, head_tree = observation.get("expected_tree"), observation.get("head_tree")
    commit_matches = (expected_tree == head_tree
                      if expected_tree and head_tree and observation.get("head_unchanged") else None)
    index_tree = observation.get("current_index_tree")
    index_matches = (expected_tree == index_tree
                     if expected_tree and index_tree and observation.get("real_index_unchanged") else None)
    committed_mismatches = []
    if "head_entries" in observation:
        head_entries = observation["head_entries"]
        for path in sorted(set(expected) | set(head_entries)):
            want, have = expected.get(path), head_entries.get(path)
            if ((want is None) != (have is None)
                    or (want and have and (want["mode"], want["oid"]) != (have["mode"], have["oid"]))):
                committed_mismatches.append({"path": path, "expected": want, "replay_head": have})
    submission_status = ("mismatch" if mismatches or commit_matches is False else
                         "unverified" if unverified or commit_matches is None else "matched")
    return {
        "status": working_status, "working_tree_status": working_status,
        "submission_state_status": submission_status,
        "submitted_commit_tree_matches": commit_matches,
        "working_tree_matches_submitted_commit": working_matches,
        "index_tree_matches_submitted_commit": index_matches,
        "expected_tree": expected_tree, "head_tree": head_tree,
        "current_index_tree": index_tree,
        "committed_tree_mismatches": committed_mismatches,
        "tracked_tree_matches": working_matches,
        "tracked_tree_matches_compatibility": "Alias of working_tree_matches_submitted_commit; this alone does not validate the submitted committed HEAD tree.",
        "expected_tracked_files": len(expected), "compared_paths": len(names),
        "matched_existing_files": matched, "verified_absent_paths": absent,
        "mismatches": mismatches, "unverified": unverified,
        "oracle_scope": "The archived patch encodes git diff --binary BASE HEAD; expected_tree is the historical submitted committed tree.",
        "claim_scope": "Committed HEAD tree identity and, separately, literal working-tree bytes against an isolated checkout using the expected tree's .gitattributes, plus Git modes, symlinks, and deletions.",
        "expected_checkout_policy": "Use only expected-tree attributes, disable inherited/system/global Git configuration, refuse external content filters, and never normalize actual replay bytes.",
        "not_established": ["untracked and ignored files match the historical terminal state",
                            "dependencies or /tmp match the historical terminal state",
                            "Git staging, commit identities, or live process state match history"],
    }


# Standard-library collector, executed inside the subject container. Tests run
# this same collector against synthetic Git fixtures without running any subject
# source code. It only invokes Git plumbing and reads file metadata/contents.
_COLLECT = r'''
import hashlib,json,os,shutil,stat,subprocess,sys,tempfile
request=json.load(sys.stdin)
root=request.get('root','/app')
base=request['base_commit']
patch=request['patch']
scratch=tempfile.mkdtemp(prefix='expected-tree-',dir=request['scratch_parent'])
result={}
def git(*args,env=None,input_bytes=None):
    process=subprocess.run(['git','-c','safe.directory='+root,'-C',root,*args],
                           env=env,input=input_bytes,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    if process.returncode:
        raise RuntimeError(json.dumps({'argv':list(args),'returncode':process.returncode,
                                       'stderr':process.stderr.decode(errors='replace')}))
    return process.stdout
def index_entries(data):
    entries={}
    for row in data.split(b'\0'):
        if not row:continue
        header,path=row.split(b'\t',1)
        mode,oid,stage=header.split()
        path=os.fsdecode(path)
        record={'mode':mode.decode(),'oid':oid.decode(),'stage':int(stage)}
        if path in entries:
            entries[path].setdefault('other_stages',[]).append(record)
        else:entries[path]=record
    return entries
def signature(path):
    if not os.path.lexists(path):return None
    with open(path,'rb') as stream:return hashlib.sha256(stream.read()).hexdigest()
try:
    real_index=os.fsdecode(git('rev-parse','--git-path','index').strip())
    if not os.path.isabs(real_index):real_index=os.path.join(root,real_index)
    head_before=git('rev-parse','HEAD').decode().strip()
    index_before=signature(real_index)
    object_path=os.fsdecode(git('rev-parse','--git-path','objects').strip())
    if not os.path.isabs(object_path):object_path=os.path.join(root,object_path)
    # Isolate repository configuration and attributes as well as index/objects.
    # In particular, neither actual .git/info/attributes nor an actual/global
    # clean/smudge filter may rewrite expected or actual bytes.
    env={key:value for key,value in os.environ.items()
         if not key.startswith('GIT_CONFIG_') and key not in
         {'GIT_DIR','GIT_COMMON_DIR','GIT_WORK_TREE','GIT_INDEX_FILE',
          'GIT_OBJECT_DIRECTORY','GIT_ALTERNATE_OBJECT_DIRECTORIES'}}
    env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull,GIT_ATTR_NOSYSTEM='1')
    object_format='sha256' if len(base)==64 else 'sha1'
    init_args=['init','--bare','--template=']
    if object_format=='sha256':init_args.append('--object-format=sha256')
    git(*init_args,scratch+'/expected.git',env=env)
    env['GIT_DIR']=scratch+'/expected.git'
    env['GIT_WORK_TREE']=scratch+'/checkout'
    os.mkdir(env['GIT_WORK_TREE'])
    env['GIT_INDEX_FILE']=scratch+'/index'
    env['GIT_OBJECT_DIRECTORY']=scratch+'/objects'
    os.mkdir(env['GIT_OBJECT_DIRECTORY'])
    # Git's on-disk alternates format avoids environment path separators.
    os.mkdir(env['GIT_OBJECT_DIRECTORY']+'/info')
    with open(env['GIT_OBJECT_DIRECTORY']+'/info/alternates','wb') as stream:
        stream.write(os.fsencode(os.path.abspath(object_path))+b'\n')
    git('read-tree',base,env=env)
    result['base']=index_entries(git('ls-files','--stage','-z',env=env))
    # Empty patches represent an unchanged submitted tracked tree.
    if os.path.getsize(patch):git('apply','--cached','--binary','--whitespace=nowarn',patch,env=env)
    result['expected']=index_entries(git('ls-files','--stage','-z',env=env))
    result['expected_tree']=git('write-tree',env=env).decode().strip()
    result['head_tree']=git('rev-parse',head_before+'^{tree}').decode().strip()
    # HEAD paths are recorded independently of the mutable index/working tree.
    head_env=env.copy();head_env['GIT_INDEX_FILE']=scratch+'/head.index'
    git('read-tree',head_before,env=head_env)
    result['head_entries']=index_entries(git('ls-files','--stage','-z',env=head_env))
    current_index_raw=git('ls-files','--stage','-z')
    result['current_index']=index_entries(current_index_raw)
    # Never run write-tree against the real index: that could update its cache
    # or create objects in the subject repository. Rebuild it in isolation.
    current_env=env.copy();current_env['GIT_INDEX_FILE']=scratch+'/current.index'
    try:
        git('read-tree','--empty',env=current_env)
        if current_index_raw:git('update-index','-z','--index-info',env=current_env,input_bytes=current_index_raw)
        result['current_index_tree']=git('write-tree',env=current_env).decode().strip()
    except Exception as error:
        result['current_index_tree_error']=type(error).__name__+': '+str(error)
    def inspect(path,worktree=root):
        try:
            # Never follow a replacement ancestor symlink outside the tree.
            parts=path.split('/')
            for end in range(1,len(parts)):
                parent='/'.join(parts[:end])
                try:parent_info=os.lstat(os.path.join(worktree,parent))
                except (FileNotFoundError,NotADirectoryError):return {'kind':'missing'}
                if not stat.S_ISDIR(parent_info.st_mode):
                    return {'kind':'blocked_ancestor','ancestor':parent,
                            'ancestor_kind':'symlink' if stat.S_ISLNK(parent_info.st_mode) else 'non_directory'}
            full=os.path.join(worktree,path)
            try:before=os.lstat(full)
            except (FileNotFoundError,NotADirectoryError):return {'kind':'missing'}
            info={'permissions':stat.S_IMODE(before.st_mode),'size':before.st_size}
            digest=hashlib.new(object_format)
            sha=hashlib.sha256()
            if stat.S_ISLNK(before.st_mode):
                content=os.fsencode(os.readlink(full))
                digest.update(b'blob '+str(len(content)).encode()+b'\0'+content)
                sha.update(content)
                info.update(kind='symlink',mode='120000',target=os.fsdecode(content))
            elif stat.S_ISREG(before.st_mode):
                digest.update(b'blob '+str(before.st_size).encode()+b'\0')
                count=0
                with open(full,'rb') as stream:
                    while True:
                        block=stream.read(1024*1024)
                        if not block:break
                        digest.update(block);sha.update(block);count+=len(block)
                info.update(kind='file',mode='100755' if before.st_mode & stat.S_IXUSR else '100644',bytes=count)
                if count!=before.st_size:info['unstable_during_read']=True
            else:
                info['kind']='directory' if stat.S_ISDIR(before.st_mode) else 'special'
                return info
            info.update(oid=digest.hexdigest(),sha256=sha.hexdigest())
            after=os.lstat(full)
            fields=('st_dev','st_ino','st_mode','st_size','st_mtime_ns','st_ctime_ns')
            if any(getattr(before,key)!=getattr(after,key) for key in fields):
                info['unstable_during_read']=True
            return info
        except OSError as error:
            return {'kind':'unreadable','error':type(error).__name__+': '+str(error)}
    expected_names=sorted(result['expected'])
    expected_input=b''.join(os.fsencode(path)+b'\0' for path in expected_names)
    attr_raw=git('check-attr','--cached','-z','--stdin','text','eol','filter',
                 'working-tree-encoding','ident',env=env,input_bytes=expected_input)
    attr_parts=attr_raw.split(b'\0')
    attributes={path:{} for path in expected_names}
    for offset in range(0,len(attr_parts)-1,3):
        path,name,value=attr_parts[offset:offset+3]
        attributes[os.fsdecode(path)][os.fsdecode(name)]=os.fsdecode(value)
    result['expected_attributes']=attributes
    result['expected_checkout_unverified']={}
    supported=[]
    for path in expected_names:
        filter_name=attributes[path].get('filter','unspecified')
        if filter_name not in {'unspecified','unset'}:
            result['expected_checkout_unverified'][path]={
                'reason':'external_content_filter_refused','filter':filter_name}
        elif result['expected'][path]['mode']!='160000':supported.append(path)
    # Checkout-index only reads the isolated expected tree/configuration. No
    # external filter has a definition here, and paths requesting one are also
    # omitted rather than silently treated as an identity transformation.
    if supported:
        try:
            git('checkout-index','--force','-z','--stdin',env=env,
                input_bytes=b''.join(os.fsencode(path)+b'\0' for path in supported))
        except Exception as error:
            for path in supported:result['expected_checkout_unverified'][path]={
                'reason':'expected_checkout_failed','error':type(error).__name__+': '+str(error)}
    result['expected_checkout']={path:inspect(path,env['GIT_WORK_TREE']) for path in expected_names}
    result['expected_checkout_configuration']={
        'attributes_source':'expected tree only; actual info/global/system attributes excluded',
        'core.autocrlf':False,'core.eol':'native (LF in Linux subject image)',
        'external_filters':'refused; no subject/global filter definitions are loaded'}
    names=set(result['base'])|set(result['expected'])|set(result['current_index'])
    result['actual']={path:inspect(path) for path in sorted(names)}
    untracked=[os.fsdecode(path) for path in git('ls-files','--others','--exclude-standard','-z').split(b'\0') if path]
    baseline=set(request.get('baseline_untracked',[]))
    # Patch-added files can correctly remain unstaged and thus appear in Git's
    # untracked query. They are already covered by the expected-tree comparison.
    result['untracked']=[{'path':path,'origin':'baseline_image_untracked' if path in baseline else 'not_in_baseline_untracked',
                          **inspect(path)} for path in untracked if path not in names]
    result['ignored_entries']=[os.fsdecode(path) for path in git('ls-files','--others','--ignored','--exclude-standard','--directory','-z').split(b'\0') if path]
    result['ignored_inventory_scope']='Ignored directory entries may be collapsed; no recursive content equality is asserted.'
    result['head_before']=head_before
    result['head_after']=git('rev-parse','HEAD').decode().strip()
    result['real_index_sha256_before']=index_before
    result['real_index_sha256_after']=signature(real_index)
    result['real_index_unchanged']=index_before==result['real_index_sha256_after']
    result['head_unchanged']=head_before==result['head_after']
    result['object_format']=object_format
except Exception as error:
    result['construction_error']={'reason':'expected_tree_or_inventory_unavailable',
                                  'error':type(error).__name__+': '+str(error)}
finally:
    shutil.rmtree(scratch)
print(json.dumps(result,ensure_ascii=True))
'''


def validate_submission_state(runtime: Container, patch: Path, out: Path, *,
                              base_commit: str | None = None) -> dict:
    """Collect and save independently checkable evidence in a new directory.

    This executes the collector inside an already-running replay container. It
    neither starts a subject command nor repairs/transplants subject files. The
    caller must ensure no concurrent writer is changing the terminal state.
    """
    base_commit = base_commit or runtime.base_commit
    if len(base_commit) not in (40, 64) or any(c not in "0123456789abcdefABCDEF" for c in base_commit):
        raise ValueError("base_commit must be a full Git object ID")
    patch, out = Path(patch).resolve(strict=True), Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "submitted.patch"
    patch_bytes = patch.read_bytes()
    frozen.write_bytes(patch_bytes)
    remote = runtime.scratch + "/submission-state-" + uuid.uuid4().hex
    remote_patch = remote + "/submitted.patch"
    request = {"base_commit": base_commit, "patch": remote_patch,
               "scratch_parent": remote, "baseline_untracked": runtime.baseline_untracked}
    (out / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    try:
        runtime.copy_to(frozen, remote_patch)
        process = runtime._control(["python3", "-c", _COLLECT],
                                   input_bytes=json.dumps(request).encode(), timeout=180, check=False)
        (out / "collector.stdout.bin").write_bytes(process.stdout)
        (out / "collector.stderr.bin").write_bytes(process.stderr)
        if process.returncode:
            raise RuntimeError(f"State collector exited {process.returncode}; see {out}")
        observation = json.loads(process.stdout)
    finally:
        runtime._control(["rm", "-rf", "--", remote], check=False)
    observation_path = out / "observation.json"
    observation_path.write_text(json.dumps(observation, ensure_ascii=True, indent=2) + "\n")
    report = compare_tracked_tree(observation)
    report.update({"base_commit": base_commit, "runtime_initial_head": runtime.base_commit,
                   "image_id": runtime.image_id,
                   "container": runtime.name, "submitted_patch_source": str(patch),
                   "submitted_patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
                   "observation": str(observation_path),
                   "observation_sha256": hashlib.sha256(observation_path.read_bytes()).hexdigest(),
                   "untracked_files": len(observation.get("untracked", [])),
                   "ignored_entries": len(observation.get("ignored_entries", [])),
                   "output_comparison_used": False,
                   "subject_files_or_real_index_patched": False})
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    return report
