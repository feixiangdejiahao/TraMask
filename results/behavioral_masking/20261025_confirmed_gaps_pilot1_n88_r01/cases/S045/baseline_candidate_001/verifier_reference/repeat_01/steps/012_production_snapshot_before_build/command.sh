python3 -I -c '
import hashlib,json,os,stat,sys
root=sys.argv[1];rows=[]
for path in sys.argv[2:]:
    target=os.path.join(root,path)
    row={'"'"'path'"'"':path,'"'"'exists'"'"':False,'"'"'kind'"'"':'"'"'absent'"'"','"'"'bytes'"'"':None,'"'"'sha256'"'"':None}
    try:info=os.lstat(target)
    except FileNotFoundError:
        rows.append(row)
        continue
    row.update(exists=True,mode=stat.S_IMODE(info.st_mode))
    if stat.S_ISREG(info.st_mode):
        row['"'"'kind'"'"']='"'"'file'"'"'
        with open(target,'"'"'rb'"'"') as stream:data=stream.read()
    elif stat.S_ISLNK(info.st_mode):
        row['"'"'kind'"'"']='"'"'symlink'"'"'
        row['"'"'link_target'"'"']=os.readlink(target)
        data=os.fsencode(row['"'"'link_target'"'"'])
    else:
        row['"'"'kind'"'"']='"'"'directory'"'"' if stat.S_ISDIR(info.st_mode) else '"'"'special'"'"'
        rows.append(row)
        continue
    row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    rows.append(row)
print(json.dumps({'"'"'paths'"'"':rows,'"'"'hash_policy'"'"':'"'"'file_bytes_or_symlink_target_bytes'"'"'}))
' /app libs/core/langchain_core/runnables/__init__.py libs/core/langchain_core/runnables/base.py libs/core/langchain_core/runnables/coalesce.py